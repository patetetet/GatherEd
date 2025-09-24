from django.shortcuts import render, redirect
from django.conf import settings
from supabase import create_client, Client
from supabase_auth.errors import AuthApiError
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import random
from datetime import datetime, timedelta

# Initialize Supabase clients for data storage only
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
        school_id = request.POST.get('school_id')
        new_school_name = request.POST.get('new_school_name')

        if not email or not password:
            messages.error(request, 'Email and password are required.')
            return render(request, 'register.html')

        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'register.html')

        if user_type == 'student' and not school_id:
            messages.error(request, 'Student registration requires a school.')
            return render(request, 'register.html')
        elif user_type == 'administrator' and not new_school_name:
            messages.error(request, 'Administrator registration requires a new school name.')
            return render(request, 'register.html')

        try:
            # PURE DJANGO: Check if user exists in Django's User model
            if User.objects.filter(email=email).exists():
                messages.error(request, 'A user with this email already exists.')
                return render(request, 'register.html')

            # PURE DJANGO: Generate OTP and store in session
            otp = str(random.randint(100000, 999999))
            otp_expiry = datetime.now() + timedelta(minutes=10)

            # Store temp data + OTP in session
            request.session['temp_user_data'] = {
                'name': name,
                'user_type': user_type,
                'school_id': school_id,
                'new_school_name': new_school_name,
                'email': email,
                'password': password,
            }
            request.session['otp'] = otp
            request.session['otp_expiry'] = otp_expiry.isoformat()

            # PURE DJANGO: Send OTP email using Django's mail function
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

        except Exception as e:
            messages.error(request, f'Unexpected error: {e}')

    schools_response = supabase_public.table('schools').select('*').execute().data
    return render(request, 'register.html', {'schools': schools_response})


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
            school_id = temp_user_data.get('school_id')
            new_school_name = temp_user_data.get('new_school_name')

            # PURE DJANGO: Create the Django user
            user = User.objects.create_user(
                username=email,  # Use email as username
                email=email,
                password=password,
            )

            # Supabase for storage only: Create profile in your database tables using the admin client
            if user_type == 'administrator':
                if new_school_name and not school_id:
                    school_result = supabase_admin.table('schools').insert({'name': new_school_name}).execute()
                    if school_result.data:
                        school_id = school_result.data[0]['id']
                    else:
                        raise Exception("Failed to create school in Supabase.")

                if school_id:
                    admin_result = supabase_admin.table('admins').insert({
                        'id': str(user.pk),  # Use Django user's primary key as Supabase ID
                        'name': name,
                        'school_id': school_id
                    }).execute()
                    if not admin_result.data:
                        raise Exception("Failed to insert admin profile.")
                else:
                    raise Exception("No school ID for administrator.")

            elif user_type == 'student':
                if school_id:
                    student_result = supabase_admin.table('students').insert({
                        'id': str(user.pk),  # Use Django user's primary key as Supabase ID
                        'name': name,
                        'school_id': school_id
                    }).execute()
                    if not student_result.data:
                        raise Exception("Failed to insert student profile.")
                else:
                    raise Exception("No school ID for student.")

            # Clear temp session data
            for key in ['otp', 'otp_expiry', 'temp_user_data']:
                request.session.pop(key, None)

            messages.success(request, 'Account confirmed and profile created! You can now log in.')
            return redirect('login')

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

        # PURE DJANGO: Authenticate using Django's system
        user = authenticate(request, username=email, password=password)

        if user is not None:
            login(request, user)
            request.session['user_id'] = str(user.pk)  # Store Django user ID in session

            try:
                # Use Django user ID to find Supabase profile
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
                return redirect('login')

            messages.error(request, "User profile not found. Contact support.")
            return redirect('login')
        else:
            messages.error(request, "Invalid email or password.")
            return render(request, 'login.html')

    return render(request, 'login.html')


def logout_view(request):
    logout(request)
    request.session.flush()
    messages.success(request, "You have been logged out.")
    return redirect('index')


# All other views now use Django's auth system to get the user ID
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
            return redirect('login')

        schools = supabase_admin.table('schools').select('*').execute().data
        events = supabase_admin.table('events').select('*').execute().data
        announcements = supabase_admin.table('announcements').select('*').execute().data
        feedbacks = supabase_admin.table('feedbacks').select('*').execute().data

        return render(request, 'admin_dashboard.html', {
            'schools': schools,
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
            insert_result = supabase_public.table('event_registrations').insert(
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
            admin_school_result = supabase_public.table('admins').select('school_id').eq('id',
                                                                                         user_id).single().execute()
            if admin_school_result.error or not admin_school_result.data:
                messages.error(request, "Admin school not found.")
                return redirect('admin_dashboard')

            admin_school = admin_school_result.data
            title = request.POST.get('title')
            description = request.POST.get('description')
            date = request.POST.get('date')

            if not all([title, description, date]):
                messages.error(request, "All event fields are required.")
                return render(request, 'create_event.html')

            insert_result = supabase_admin.table('events').insert({
                'title': title,
                'description': description,
                'date': date,
                'school_id': admin_school['school_id']
            }).execute()
            if not insert_result.data:
                raise Exception(f"Event creation failed: {getattr(insert_result, 'error', 'Unknown error')}")

            messages.success(request, "Event created successfully!")
            return redirect('admin_dashboard')
        except Exception as e:
            messages.error(request, f"Failed to create event: {e}")
            return render(request, 'create_event.html')

    return render(request, 'create_event.html')