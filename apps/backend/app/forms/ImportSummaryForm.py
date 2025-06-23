from flask_wtf import FlaskForm
from wtforms import SelectField
from wtforms import StringField
from wtforms import TextAreaField
from wtforms import SubmitField

class ImportSummaryForm(FlaskForm):
    category_field = SelectField('Category', choices=[])
    activity_title = StringField('Activity Title')
    description = TextAreaField('Description')
    save = SubmitField('Save')
    cancel = SubmitField('Cancel')
    activity = None

    def __init__(self, *args, **kwargs):
        super(ImportSummaryForm, self).__init__(*args, **kwargs)
        # TODO - get category choices from the db