from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('verify-otp/', views.verify_otp, name='verify_otp'),  # OTP verification
    path('student_dashboard/', views.student_dashboard, name='student_dashboard'),
    path('event_listing/', views.event_listing, name='event_listing'),
    path('events/register/<int:event_id>/', views.event_register, name='event_register'),
    path('events/create/', views.create_event, name='create_event'),
    path('admin_dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('create_event/', views.create_event, name='create_event'),
]
