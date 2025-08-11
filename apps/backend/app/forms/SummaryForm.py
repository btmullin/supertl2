# app/forms/activity_filters.py
from flask_wtf import FlaskForm
from wtforms import SelectMultipleField, SelectField, DateField, SubmitField
from wtforms.validators import Optional

class SummaryFilterForm(FlaskForm):
    categories = SelectMultipleField("Categories", coerce=int, validators=[Optional()])
    sport_types = SelectMultipleField("Sport types", validators=[Optional()])
    is_training = SelectField(
        "Training only",
        choices=[("", "Any"), ("1", "Yes"), ("0", "No")],
        validators=[Optional()],
        default=""
    )
    date_start = DateField("From", format="%Y-%m-%d", validators=[Optional()])
    date_end = DateField("To", format="%Y-%m-%d", validators=[Optional()])

    submit = SubmitField("Apply")
