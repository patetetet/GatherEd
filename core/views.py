from django.shortcuts import render, redirect
from django.conf import settings
from supabase import create_client, Client
from supabase_auth.errors import AuthApiError
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from urllib.parse import urlparse, parse_qs

# Initialize Supabase clients
supabase_public: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
supabase_admin: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def set_user_session(request):
    """Helper to set the user session on the public client if tokens are available."""
    access_token = request.session.get('access_token')
    refresh_token = request.session.get('refresh_token')
    if access_token and refresh_token:
        try:
            supabase_public.auth.set_session(access_token, refresh_token)
            return True
        except Exception:
            # If setting session fails, flush invalid session
            request.session.flush()
            return False
    return False


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
            # Sign up user in Supabase Auth (errors are raised as exceptions; no .error attribute on success)
            result = supabase_public.auth.sign_up({"email": email, "password": password})

            # On success, check if user was created (no need for .error check)
            if not result.user:
                messages.error(request, 'Registration failed: No user created.')
                return render(request, 'register.html')

            # Save temp data for profile creation after email confirmation
            request.session['temp_user_data'] = {
                'name': name,
                'user_type': user_type,
                'school_id': school_id,
                'new_school_name': new_school_name,
            }

            messages.success(request, 'Registration successful! Please check your email to confirm your account.')
            return redirect('email_confirmation_sent')

        except AuthApiError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f'Unexpected error: {e}')

    # Load schools for dropdown (anon access)
    schools_response = supabase_public.table('schools').select('*').execute().data
    return render(request, 'register.html', {'schools': schools_response})


def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')

        if not email or not password:
            messages.error(request, 'Email and password are required.')
            return render(request, 'login.html')

        try:
            # Sign in user (errors are raised as exceptions; no .error attribute on success)
            res = supabase_public.auth.sign_in_with_password({"email": email, "password": password})

            # On success, check if session was received
            if not res.session:
                messages.error(request, 'Login failed: No session received.')
                return render(request, 'login.html')

            request.session['access_token'] = res.session.access_token
            request.session['refresh_token'] = res.session.refresh_token
            user_id = res.user.id if res.user else None
            if not user_id:
                messages.error(request, 'Login failed: No user ID received.')
                return render(request, 'login.html')
            request.session['user_id'] = user_id

            # Set session on client for queries
            set_user_session(request)

            # Check role with authenticated client
            admin_check = supabase_public.table('admins').select('id').eq('id', user_id).limit(1).execute().data
            if admin_check:
                return redirect('admin_dashboard')

            student_check = supabase_public.table('students').select('id').eq('id', user_id).limit(1).execute().data
            if student_check:
                return redirect('student_dashboard')

            messages.error(request, "User  profile not found. Contact support.")
            return redirect('login')

        except AuthApiError as e:
            messages.error(request, str(e))
        except Exception as e:
            messages.error(request, f'Login error: {e}')

    return render(request, 'login.html')


def logout_view(request):
    # Optional: sign out from Supabase
    try:
        set_user_session(request)  # Set if tokens present
        supabase_public.auth.sign_out()
    except:
        pass
    request.session.flush()
    messages.success(request, "You have been logged out.")
    return redirect('index')


def auth_callback(request):
    try:
        fragment = urlparse(request.get_full_path()).fragment
        query_params = parse_qs(fragment)
        access_token = query_params.get('access_token', [None])[0]
        refresh_token = query_params.get('refresh_token', [None])[0]

        if not access_token or not refresh_token:
            messages.error(request, "Authentication failed. No access or refresh token found.")
            return redirect('login')

        # Set in session and on client
        request.session['access_token'] = access_token
        request.session['refresh_token'] = refresh_token
        supabase_public.auth.set_session(access_token, refresh_token)

        # Get current user (no arg needed after set_session)
        auth_response = supabase_public.auth.get_user()
        user_id = auth_response.user.id

        request.session['user_id'] = user_id

        # Use stored session data for profile creation
        temp_user_data = request.session.get('temp_user_data')
        if temp_user_data:
            name = temp_user_data.get('name')
            user_type = temp_user_data.get('user_type')

            if user_type == 'administrator':
                new_school_name = temp_user_data.get('new_school_name')
                school_id = temp_user_data.get('school_id')

                if new_school_name and not school_id:
                    school_data = supabase_admin.table('schools').insert({'name': new_school_name}).execute().data
                    if school_data:
                        school_id = school_data[0]['id']
                    else:
                        raise Exception("Failed to create school")

                if school_id:
                    supabase_admin.table('admins').insert(
                        {'id': user_id, 'name': name, 'school_id': school_id}
                    ).execute()

            elif user_type == 'student':
                school_id = temp_user_data.get('school_id')
                if school_id:
                    supabase_admin.table('students').insert(
                        {'id': user_id, 'name': name, 'school_id': school_id}
                    ).execute()

            del request.session['temp_user_data']

        # Redirect based on role (with session set, RLS should allow)
        admin_check = supabase_public.table('admins').select('id').eq('id', user_id).execute().data
        if admin_check:
            return redirect('admin_dashboard')

        student_check = supabase_public.table('students').select('id').eq('id', user_id).execute().data
        if student_check:
            return redirect('student_dashboard')

        messages.error(request, "User  profile not found.")
        return redirect('login')
    except Exception as e:
        messages.error(request, f"Auth callback error: {e}")
        return redirect('login')


@login_required
def student_dashboard(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    set_user_session(request)
    try:
        events = supabase_public.table('events').select('*').execute().data
        announcements = supabase_public.table('announcements').select('*').execute().data
        registrations = supabase_public.table('event_registrations').select('*, events(*)').eq('user_id',
                                                                                               user_id).execute().data

        context = {
            'events': events,
            'announcements': announcements,
            'registered_events': [r['events'] for r in registrations if 'events' in r],
        }
        return render(request, 'student_dashboard.html', context)
    except Exception as e:
        messages.error(request, f"Failed to load student dashboard: {e}")
        return redirect('index')


@login_required
def admin_dashboard(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    set_user_session(request)
    try:
        # Verify admin role with authenticated client
        admin_check = supabase_public.table('admins').select('id').eq('id', user_id).execute().data
        if not admin_check:
            messages.error(request, "Access denied.")
            return redirect('login')

        # Use admin client for full access
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
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    set_user_session(request)
    try:
        existing = supabase_public.table('event_registrations').select('*').eq('user_id', user_id).eq('event_id',
                                                                                                      event_id).execute().data
        if existing:
            messages.info(request, "You are already registered.")
        else:
            supabase_public.table('event_registrations').insert({'user_id': user_id, 'event_id': event_id}).execute()
            messages.success(request, "Registered successfully!")
        return redirect('student_dashboard')
    except Exception as e:
        messages.error(request, f"Event registration failed: {e}")
        return redirect('event_listing')


def email_confirmation_sent(request):
    return render(request, 'email_confirmation_sent.html')


@login_required
def event_listing(request):
    set_user_session(request)
    try:
        events = supabase_public.table('events').select('*').execute().data
        return render(request, 'event_listing.html', {'events': events})
    except Exception as e:
        messages.error(request, f"Failed to load events: {e}")
        return redirect('index')


@login_required
def create_event(request):
    user_id = request.session.get('user_id')
    if not user_id:
        return redirect('login')

    set_user_session(request)
    if request.method == 'POST':
        try:
            # Get admin school with authenticated client
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
                return redirect('create_event')

            supabase_admin.table('events').insert({
                'title': title,
                'description': description,
                'date': date,
                'school_id': admin_school['school_id']
            }).execute()

            messages.success(request, "Event created successfully!")
            return redirect('admin_dashboard')
        except Exception as e:
            messages.error(request, f"Failed to create event: {e}")
            return redirect('admin_dashboard')

    return render(request, 'create_event.html')
