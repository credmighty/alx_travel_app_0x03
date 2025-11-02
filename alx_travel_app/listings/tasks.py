from celery import shared_task
from django.core.mail import send_mail

@shared_task
def send_booking_confirmation_email(user_email, trip_title):
    subject = "Booking Confirmation"
    message = f"Your booking for '{trip_title}' has been confirmed. 🎉"
    from_email = "noreply@travelapp.com"

    send_mail(subject, message, from_email, [user_email])
    print(f"📧 Confirmation email sent to {user_email}")