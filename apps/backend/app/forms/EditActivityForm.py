from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, BooleanField, SelectField, HiddenField, SubmitField
from wtforms.validators import Optional

class EditActivityForm(FlaskForm):
    activityId = HiddenField("Activity ID")

    workoutTypeId = SelectField("Workout Type", coerce=int, validators=[Optional()])
    categoryId = SelectField("Category", coerce=int, validators=[Optional()])

    notes = TextAreaField("Notes", validators=[Optional()])
    tags = StringField("Tags", validators=[Optional()])
    isTraining = SelectField(
        "Is Training?",
        coerce=int,
        choices=[
            (2, "Unknown"),
            (1, "Yes"),
            (0, "No"),
        ],
        validators=[Optional()],
    )

    submit = SubmitField("Save")
    cancel = SubmitField("Cancel")