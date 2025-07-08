from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, SubmitField
from wtforms.validators import DataRequired, Optional

class CategoryForm(FlaskForm):
    name = StringField("Category Name", validators=[DataRequired()])
    parent_id = SelectField("Parent Category", coerce=int, validators=[Optional()])
    submit = SubmitField("Save")
    cancel = SubmitField("Cancel")