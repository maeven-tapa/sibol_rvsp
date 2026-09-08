from django.urls import path
from . import views
from . import gate_views

urlpatterns = [
    path('register/details/', views.account_details, name='account_details'),
    path('admin-login/', views.admin_sign_in, name='admin_login'),
    path('register/check-id/', views.check_student, name='check_student'),
    path("", views.home, name="home"), path("register/", views.register, name="register"),
    path("login/", views.sign_in, name="login"), path("logout/", views.sign_out, name="logout"),
    path("tickets/", views.tickets, name="tickets"), path("buy/<str:ticket_type>/", views.buy_ticket, name="buy_ticket"),
    path('tickets/reserve/', views.reserve_guests, name='reserve_guests'), path('tickets/transfer/', views.transfer_ticket, name='transfer_ticket'), path('tickets/transfer/<int:transfer_id>/accept/', views.accept_transfer, name='accept_transfer'),
    path("purchase/", views.purchase, name="purchase"),
    path("dashboard/", views.dashboard, name="dashboard"), path("gate/", gate_views.setup, name="gate"),
    path('program-flow/', views.program_flow, name='program_flow'),
    path('gate/scanner/', gate_views.scanner, name='gate_scanner'),
    path('gate/scan/', gate_views.scan, name='gate_scan'),
]
