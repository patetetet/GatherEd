from django.shortcuts import render, redirect
from django.conf import settings
from supabase import create_client, Client
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import random
from datetime import datetime, timedelta
import re

# Initialize Supabase clients for data storage
supabase_public: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
supabase_admin: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def index(request):
    return render(request, 'index.html')


def register(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        name = request.POST.get('name')
        user_type = request.POST.get('user_type')
        cit_id = request.POST.get('cit_id')

        if not email or not password or not cit_id:
            messages.error(request, 'All fields are required.')
            return render(request, 'register.html')

        # Check password match before other validations
        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'register.html')

        # Enforce @cit.edu email domain
        if not email.endswith('@cit.edu'):
            messages.error(request, 'Registration is limited to @cit.edu email addresses only.')
            return render(request, 'register.html')

        # Clean the input by removing any dashes
        cleaned_cit_id = cit_id.replace('-', '')

        # Check if the cleaned ID is exactly 9 digits
        if not cleaned_cit_id.isdigit() or len(cleaned_cit_id) != 9:
            messages.error(request, 'The ID must be exactly 9 digits long.')
            return render(request, 'register.html')

        # Automatically format the ID with dashes for storage and check
        formatted_cit_id = f"{cleaned_cit_id[:2]}-{cleaned_cit_id[2:6]}-{cleaned_cit_id[6:]}"

        # Check if user exists in Django's User model
        if User.objects.filter(email=email).exists():
            messages.error(request, 'A user with this email already exists.')
            return render(request, 'register.html')

        # Check for unique user ID in both Supabase tables using the formatted ID
        student_id_check = supabase_public.table('students').select('cit_id').eq('cit_id',
                                                                                 formatted_cit_id).execute().data
        admin_id_check = supabase_public.table('admins').select('cit_id').eq('cit_id', formatted_cit_id).execute().data

        if student_id_check or admin_id_check:
            messages.error(request, 'This ID is already registered.')
            return render(request, 'register.html')

        # Generate OTP and store in session
        otp = str(random.randint(100000, 999999))
        otp_expiry = datetime.now() + timedelta(minutes=10)

        request.session['temp_user_data'] = {
            'name': name,
            'user_type': user_type,
            'email': email,
            'password': password,
            'cit_id': formatted_cit_id,  # Store the new formatted ID
        }
        request.session['otp'] = otp
        request.session['otp_expiry'] = otp_expiry.isoformat()

        # Send OTP email
        subject = 'GatherEd Account Confirmation'
        html_message = render_to_string('emails/otp_email.html', {
            'otp': otp,
            'name': name,
        })
        plain_message = strip_tags(html_message)
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            html_message=html_message,
        )

        messages.success(request,
                         f'Registration successful! A 6-digit OTP has been sent to {email}. Enter it to confirm.')
        return redirect('verify_otp')

    return render(request, 'register.html')


def verify_otp(request):
    if request.method == 'POST':
        entered_otp = request.POST.get('otp')
        stored_otp = request.session.get('otp')
        otp_expiry_str = request.session.get('otp_expiry')
        temp_user_data = request.session.get('temp_user_data')

        if not all([entered_otp, stored_otp, otp_expiry_str, temp_user_data]):
            messages.error(request, 'Session expired or invalid. Please register again.')
            for key in ['otp', 'otp_expiry', 'temp_user_data']:
                request.session.pop(key, None)
            return redirect('register')

        try:
            otp_expiry = datetime.fromisoformat(otp_expiry_str)
            if datetime.now() > otp_expiry:
                messages.error(request, 'OTP has expired. Please register again.')
                for key in ['otp', 'otp_expiry', 'temp_user_data']:
                    request.session.pop(key, None)
                return redirect('register')
        except ValueError:
            messages.error(request, 'Invalid session. Please register again.')
            return redirect('register')

        if entered_otp != stored_otp:
            messages.error(request, 'Invalid OTP. Please try again.')
            return render(request, 'otp_confirmation.html')

        try:
            email = temp_user_data['email']
            password = temp_user_data['password']
            name = temp_user_data.get('name')
            user_type = temp_user_data.get('user_type')
            cit_id = temp_user_data.get('cit_id')

            # Create the Django user
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
            )

            # Create profile in Supabase with the new field
            if user_type == 'administrator':
                admin_result = supabase_admin.table('admins').insert({
                    'id': str(user.pk),
                    'name': name,
                    'cit_id': cit_id
                }).execute()
                if not admin_result.data:
                    raise Exception("Failed to insert admin profile.")

            elif user_type == 'student':
                student_result = supabase_admin.table('students').insert({
                    'id': str(user.pk),
                    'name': name,
                    'cit_id': cit_id
                }).execute()
                if not student_result.data:
                    raise Exception("Failed to insert student profile.")

            # Clear temp session data
            for key in ['otp', 'otp_expiry', 'temp_user_data']:
                request.session.pop(key, None)

            messages.success(request, 'Account confirmed and profile created! You can now log in.')
            return redirect('login_view')

        except Exception as e:
            messages.error(request, f'Confirmation failed: {str(e)}')

    return render(request, 'otp_confirmation.html')


def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')

        if not email or not password:
            messages.error(request, 'Email and password are required.')
            return render(request, 'login.html')

        user = authenticate(request, username=email, password=password)

        if user is not None:
            login(request, user)

            try:
                admin_check = supabase_public.table('admins').select('id').eq('id', str(user.pk)).limit(
                    1).execute().data
                if admin_check:
                    return redirect('admin_dashboard')

                student_check = supabase_public.table('students').select('id').eq('id', str(user.pk)).limit(
                    1).execute().data
                if student_check:
                    return redirect('student_dashboard')
            except Exception as e:
                messages.error(request, f"Error checking user profile: {e}")
                return redirect('login_view')

            messages.error(request, "User profile not found. Contact support.")
            return render(request, 'login.html')
        else:
            messages.error(request, "Invalid email or password.")
            return render(request, 'login.html')

    return render(request, 'login.html')


def logout_view(request):
    logout(request)
    request.session.flush()
    messages.success(request, "You have been logged out.")
    return redirect('index')


@login_required
def student_dashboard(request):
    user_id = str(request.user.pk)
    try:
        events = supabase_public.table('events').select('*').execute().data
        announcements = supabase_public.table('announcements').select('*').execute().data
        registrations = supabase_public.table('event_registrations').select('*, events(*)').eq('user_id',
                                                                                               user_id).execute().data
        context = {
            'events': events,
            'announcements': announcements,
            'registered_events': [r.get('events', {}) for r in registrations],
        }
        return render(request, 'student_dashboard.html', context)
    except Exception as e:
        messages.error(request, f"Failed to load student dashboard: {e}")
        return redirect('index')


@login_required
def admin_dashboard(request):
    user_id = str(request.user.pk)
    try:
        admin_check = supabase_public.table('admins').select('id').eq('id', user_id).execute().data
        if not admin_check:
            messages.error(request, "Access denied.")
            return redirect('login_view')

        events = supabase_public.table('events').select('*').execute().data
        announcements = supabase_public.table('announcements').select('*').execute().data
        feedbacks = supabase_public.table('feedbacks').select('*').execute().data

        return render(request, 'admin_dashboard.html', {
            'events': events,
            'announcements': announcements,
            'feedbacks': feedbacks,
        })
    except Exception as e:
        messages.error(request, f"Failed to load admin dashboard: {e}")
        return redirect('index')


@login_required
def event_register(request, event_id):
    user_id = str(request.user.pk)
    try:
        existing = supabase_public.table('event_registrations').select('*').eq('user_id', user_id).eq('event_id',
                                                                                                      event_id).execute().data
        if existing:
            messages.info(request, "You are already registered.")
        else:
            insert_result = supabase_admin.table('event_registrations').insert(
                {'user_id': user_id, 'event_id': event_id}).execute()
            if not insert_result.data:
                raise Exception(f"Registration insert failed: {getattr(insert_result, 'error', 'Unknown error')}")
            messages.success(request, "Registered successfully!")
        return redirect('student_dashboard')
    except Exception as e:
        messages.error(request, f"Event registration failed: {e}")
        return redirect('event_listing')


@login_required
def event_listing(request):
    try:
        events = supabase_public.table('events').select('*').execute().data
        return render(request, 'event_listing.html', {'events': events})
    except Exception as e:
        messages.error(request, f"Failed to load events: {e}")
        return redirect('index')


@login_required
def create_event(request):
    user_id = str(request.user.pk)
    if request.method == 'POST':
        try:
            # Check if the user is an admin
            admin_check = supabase_public.table('admins').select('id').eq('id', user_id).execute().data
            if not admin_check:
                messages.error(request, "Access denied.")
                return redirect('admin_dashboard')

            title = request.POST.get('title')
            description = request.POST.get('description')
            date = request.POST.get('date')

            if not all([title, description, date]):
                messages.error(request, "All event fields are required.")
                return render(request, 'create_event.html')

            insert_result = supabase_admin.table('events').insert({
                'title': title,
                'description': description,
                'date': date
            }).execute()
            if not insert_result.data:
                raise Exception(f"Event creation failed: {getattr(insert_result, 'error', 'Unknown error')}")

            messages.success(request, "Event created successfully!")
            return redirect('admin_dashboard')
        except Exception as e:
            messages.error(request, f"Failed to create event: {e}")
            return render(request, 'create_event.html')

    return render(request, 'create_event.html')