from __future__ import annotations

from django import forms

from .models import ContactMessage


class ContactForm(forms.ModelForm):
    website = forms.CharField(required=False, widget=forms.HiddenInput, label="Leave empty")

    class Meta:
        model = ContactMessage
        fields = ["name", "email", "topic", "message"]
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "message": forms.Textarea(attrs={"rows": 6, "maxlength": 4000}),
        }
        labels = {"topic": "What can we help with?"}

    def clean_message(self) -> str:
        message = self.cleaned_data["message"].strip()
        if len(message) < 10:
            raise forms.ValidationError("Please add a little more detail (at least 10 characters).")
        return message

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("website"):
            raise forms.ValidationError("Your message could not be sent.")
        return cleaned
