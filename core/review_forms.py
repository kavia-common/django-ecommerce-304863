from django import forms


class ReviewForm(forms.Form):
    """Template form for creating/updating a review."""

    rating = forms.ChoiceField(
        choices=[(i, str(i)) for i in range(5, 0, -1)],
        required=True,
        label="Rating",
        widget=forms.Select(attrs={"class": "custom-select d-block w-100"}),
    )
    title = forms.CharField(
        required=False,
        max_length=200,
        label="Title (optional)",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Short summary"}),
    )
    body = forms.CharField(
        required=True,
        label="Review",
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "Share your experience..."}),
    )

    def clean_body(self):
        body = (self.cleaned_data.get("body") or "").strip()
        if not body:
            raise forms.ValidationError("Please enter your review text.")
        if len(body) < 10:
            raise forms.ValidationError("Review text is too short (min 10 characters).")
        return body
