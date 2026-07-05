from django import forms
from django.utils.translation import gettext_lazy as _


class PeerCreateForm(forms.Form):
    name = forms.CharField(
        max_length=100,
        label=_("Device name"),
        help_text=_("A friendly name for this client device (e.g. 'iPhone', 'Laptop')."),
        widget=forms.TextInput(attrs={"class": "form-control", "autofocus": True}),
    )
    dns = forms.CharField(
        max_length=255,
        label=_("DNS servers"),
        initial="1.1.1.1,1.0.0.1",
        required=False,
        help_text=_("Comma-separated DNS servers to include in the client config."),
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    manual_ip = forms.GenericIPAddressField(
        label=_("Assign specific IP (optional)"),
        required=False,
        help_text=_(
            "Leave blank to auto-assign the next available IP in the subnet. "
            "If provided, must be a free address within the interface subnet."
        ),
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. 10.0.0.5"}),
    )
