from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, BooleanField, SelectField, HiddenField, SubmitField
from wtforms.validators import Optional

class EditExtraForm(FlaskForm):
    activityId = HiddenField("Activity ID")

    workoutTypeId = SelectField("Workout Type", coerce=int, validators=[Optional()])
    categoryId = SelectField("Category", coerce=int, validators=[Optional()])

    notes = TextAreaField("Notes", validators=[Optional()])
    tags = StringField("Tags", validators=[Optional()])
    isTraining = BooleanField("Is Training?")

    submit = SubmitField("Save")
    cancel = SubmitField("Cancel")