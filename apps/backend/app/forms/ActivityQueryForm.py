# app/forms/activity_filters.py
from flask_wtf import FlaskForm
from wtforms import SelectMultipleField, SelectField, DateField, SubmitField, IntegerField
from wtforms.validators import Optional

class ActivityQueryFilterForm(FlaskForm):
    categories = SelectMultipleField("Categories", coerce=int, validators=[Optional()])
    is_training = SelectField(
        "Training only",
        choices=[("", "Any"), ("1", "Yes"), ("0", "No")],
        validators=[Optional()],
        default="1"
    )
    min_time = IntegerField("Min Time (minutes)", validators=[Optional()])
    max_time = IntegerField("Max Time (minutes)", validators=[Optional()])
    date_start = DateField("From", format="%Y-%m-%d", validators=[Optional()])
    date_end = DateField("To", format="%Y-%m-%d", validators=[Optional()])

    submit = SubmitField("Apply")
