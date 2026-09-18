from django import forms

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


class DatasetUploadForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Leave blank to use the file name"}
        ),
    )
    file = forms.FileField(widget=forms.ClearableFileInput(attrs={"class": "form-control"}))

    def clean_file(self):
        uploaded_file = self.cleaned_data["file"]
        ext = uploaded_file.name.rsplit(".", 1)[-1].lower() if "." in uploaded_file.name else ""
        if ext not in ("csv", "xlsx"):
            raise forms.ValidationError("Please upload a .csv or .xlsx file.")
        if uploaded_file.size > MAX_UPLOAD_SIZE:
            raise forms.ValidationError("File is too large (max 10 MB).")
        return uploaded_file


class ManualDatasetForm(forms.Form):
    name = forms.CharField(
        max_length=255, widget=forms.TextInput(attrs={"class": "form-control"})
    )
    columns = forms.CharField(
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "e.g. Name, Email, Phone"}
        ),
        help_text="Comma-separated column names.",
    )

    def clean_columns(self):
        raw = self.cleaned_data["columns"]
        columns = [c.strip() for c in raw.split(",") if c.strip()]
        if not columns:
            raise forms.ValidationError("Enter at least one column name.")
        if len(set(columns)) != len(columns):
            raise forms.ValidationError("Column names must be unique.")
        return columns


class DynamicRowForm(forms.Form):
    """A form whose fields are built at runtime from a dataset's column list."""

    def __init__(self, *args, columns=None, **kwargs):
        super().__init__(*args, **kwargs)
        for column in columns or []:
            self.fields[column] = forms.CharField(
                label=column,
                required=False,
                widget=forms.TextInput(attrs={"class": "form-control"}),
            )


def build_row_form(columns, data=None, initial=None):
    return DynamicRowForm(data, columns=columns, initial=initial)
