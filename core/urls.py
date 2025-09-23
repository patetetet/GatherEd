# core/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('register/', views.register, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('student_dashboard/', views.student_dashboard, name='student_dashboard'),
    path('admin_dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('event_listing/', views.event_listing, name='event_listing'),
    path('events/register/<int:event_id>/', views.event_register, name='event_register'),
    path('register/confirmation-sent/', views.email_confirmation_sent, name='email_confirmation_sent'),
    path('auth/callback/', views.auth_callback, name='auth_callback'),
]