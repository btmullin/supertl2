from flask_wtf import FlaskForm
from wtforms import StringField, DateField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Length, ValidationError

class SeasonCreateForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    start_date = DateField("Start date", validators=[DataRequired()], format="%Y-%m-%d")
    end_date = DateField("End date", validators=[DataRequired()], format="%Y-%m-%d")
    is_active = BooleanField("Active", default=True)
    submit = SubmitField("Create season")

    def validate_end_date(self, field):
        if self.start_date.data and field.data and field.data < self.start_date.data:
            raise ValidationError("End date must be on or after start date.")
