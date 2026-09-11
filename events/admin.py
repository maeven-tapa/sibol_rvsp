from django.contrib import admin
from .models import Ticket, Student, Faculty, GateAdmission

@admin.register(GateAdmission)
class GateAdmissionAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'operator', 'port', 'relay', 'status', 'created_at')
    list_filter = ('status', 'relay')
    readonly_fields = ('ticket', 'operator', 'port', 'relay', 'status', 'created_at', 'detail')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('tupc_id', 'name', 'program_section')
    search_fields = ('tupc_id', 'name', 'program_section')

@admin.register(Faculty)
class FacultyAdmin(admin.ModelAdmin):
    list_display = ('employee_id', 'name', 'department', 'campus', 'user')
    list_filter = ('campus',)
    search_fields = ('employee_id', 'name', 'department', 'user__username')

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("code", "owner", "ticket_type", "purchased_at", "checked_in_at")
    list_filter = ("ticket_type", "checked_in_at")
    search_fields = ("code", "owner__username", "owner__email")
    readonly_fields = ("code", "purchased_at", "checked_in_at")
