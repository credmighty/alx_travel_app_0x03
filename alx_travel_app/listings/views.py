import os
import requests
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticatedOrReadOnly, IsAuthenticated
from .models import Listing, Booking, Payment
from .serializers import ListingSerializer, BookingSerializer, PaymentSerializer
from .tasks import send_booking_confirmation_email


class ListingViewSet(viewsets.ModelViewSet):
    queryset = Listing.objects.all()
    serializer_class = ListingSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]


class BookingViewSet(viewsets.ModelViewSet):
    queryset = Booking.objects.all()
    serializer_class = BookingSerializer
    # permission_classes = [IsAuthenticated]

    def perform_create(self, serializer):
        booking = serializer.save(guest=self.request.user)
        # Trigger async email task
        send_booking_confirmation_email.delay(str(booking.booking_id))


class PaymentViewSet(viewsets.ModelViewSet):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    # permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'], url_path='initiate')
    def initiate_payment(self, request):
        """Initiate payment with Chapa"""
        booking_id = request.data.get('booking_id')

        try:
            booking = Booking.objects.get(booking_id=booking_id)
        except Booking.DoesNotExist:
            return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

        # Create payment record
        payment = Payment.objects.create(
            booking=booking,
            amount=booking.total_price,
            reference=f"BK-{booking.booking_id}"
        )

        # Prepare Chapa payment request
        chapa_url = "https://api.chapa.co/v1/transaction/initialize"
        headers = {
            "Authorization": f"Bearer {os.getenv('CHAPA_SECRET_KEY')}",
            "Content-Type": "application/json"
        }

        payload = {
            "amount": str(booking.total_price),
            "currency": "ETB",
            "email": request.user.email,
            "first_name": request.user.first_name,
            "last_name": request.user.last_name,
            "tx_ref": payment.reference,
            "callback_url": request.build_absolute_uri('/api/payments/verify/'),
            "return_url": request.data.get('return_url', 'http://localhost:3000/payment/success'),
            "customization": {
                "title": f"Payment for {booking.listing.title}",
                "description": f"Booking from {booking.check_in_date} to {booking.check_out_date}"
            }
        }

        try:
            response = requests.post(chapa_url, json=payload, headers=headers)
            response_data = response.json()

            if response.status_code == 200 and response_data.get('status') == 'success':
                payment.transaction_id = response_data['data']['tx_ref']
                payment.save()

                return Response({
                    'payment_url': response_data['data']['checkout_url'],
                    'reference': payment.reference,
                    'status': 'success'
                }, status=status.HTTP_200_OK)
            else:
                payment.status = 'failed'
                payment.save()
                return Response({'error': response_data.get('message', 'Payment initiation failed')},
                                status=status.HTTP_400_BAD_REQUEST)

        except requests.exceptions.RequestException as e:
            payment.status = 'failed'
            payment.save()
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path='verify')
    def verify_payment(self, request):
        """Verify payment status with Chapa"""
        tx_ref = request.query_params.get('tx_ref')

        if not tx_ref:
            return Response({'error': 'Transaction reference is required'},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            payment = Payment.objects.get(reference=tx_ref)
        except Payment.DoesNotExist:
            return Response({'error': 'Payment not found'}, status=status.HTTP_404_NOT_FOUND)

        # Verify with Chapa
        chapa_url = f"https://api.chapa.co/v1/transaction/verify/{tx_ref}"
        headers = {
            "Authorization": f"Bearer {os.getenv('CHAPA_SECRET_KEY')}"
        }

        try:
            response = requests.get(chapa_url, headers=headers)
            response_data = response.json()

            if response.status_code == 200 and response_data.get('status') == 'success':
                chapa_status = response_data['data']['status']

                if chapa_status == 'success':
                    payment.status = 'completed'
                    payment.booking.status = 'confirmed'
                    payment.booking.save()
                else:
                    payment.status = 'failed'

                payment.save()

                return Response({
                    'reference': payment.reference,
                    'status': payment.status,
                    'amount': str(payment.amount)
                }, status=status.HTTP_200_OK)
            else:
                return Response({'error': 'Verification failed'},
                                status=status.HTTP_400_BAD_REQUEST)

        except requests.exceptions.RequestException as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)