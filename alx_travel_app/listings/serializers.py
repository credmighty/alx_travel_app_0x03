from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Listing, Booking, Review, Payment


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']


class ReviewSerializer(serializers.ModelSerializer):
    reviewer = UserSerializer(read_only=True)

    class Meta:
        model = Review
        fields = ['review_id', 'reviewer', 'rating', 'comment', 'created_at']


class ListingSerializer(serializers.ModelSerializer):
    host = UserSerializer(read_only=True)
    reviews = ReviewSerializer(many=True, read_only=True)
    average_rating = serializers.SerializerMethodField()
    review_count = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = [
            'listing_id', 'title', 'description', 'price_per_night', 'location',
            'amenities', 'host', 'created_at', 'updated_at', 'is_available',
            'reviews', 'average_rating', 'review_count'
        ]

    def get_average_rating(self, obj):
        reviews = obj.reviews.all()
        if reviews:
            return sum(review.rating for review in reviews) / len(reviews)
        return 0

    def get_review_count(self, obj):
        return obj.reviews.count()


class BookingSerializer(serializers.ModelSerializer):
    listing = ListingSerializer(read_only=True)
    guest = UserSerializer(read_only=True)
    listing_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = Booking
        fields = [
            'booking_id', 'listing', 'listing_id', 'guest', 'check_in_date',
            'check_out_date', 'total_price', 'status', 'created_at'
        ]

    def validate(self, data):
        if data['check_in_date'] >= data['check_out_date']:
            raise serializers.ValidationError("Check-out date must be after check-in date.")
        return data


class PaymentSerializer(serializers.ModelSerializer):
    booking = BookingSerializer(read_only=True)
    booking_id = serializers.UUIDField(write_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Payment
        fields = [
            'payment_id', 'booking', 'booking_id', 'amount', 'transaction_id',
            'reference', 'status', 'status_display', 'payment_method',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'payment_id', 'transaction_id', 'status', 'reference',
            'created_at', 'updated_at'
        ]

    def validate_booking_id(self, value):
        """Validate that the booking exists and doesn't already have a payment"""
        try:
            booking = Booking.objects.get(booking_id=value)
        except Booking.DoesNotExist:
            raise serializers.ValidationError("Booking not found.")

        if hasattr(booking, 'payment'):
            raise serializers.ValidationError("Payment already exists for this booking.")

        return value

    def validate_amount(self, value):
        """Ensure amount is positive"""
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than zero.")
        return value