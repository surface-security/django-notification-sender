from django.urls import path

from notifications import views

urlpatterns = [path('notify/', views.notify, name='notify')]
