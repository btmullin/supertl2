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
    general_trail = SubmitField("General Trail Run")
    general_mountain_bike = SubmitField("General Mountain Bike")
    general_gravel_bike = SubmitField("General Gravel Bike")
    general_virtual_bike = SubmitField("General Virtual Bike")
    strength = SubmitField("Strength Training")
    l3_skate_roller = SubmitField("L3 Skate Roller")
    l3_classic_roller = SubmitField("L3 Classic Roller")
    general_skate_ski = SubmitField("General Skate Ski")
    general_classic_ski = SubmitField("General Classic Ski")
