from django.utils.translation import gettext_lazy as _

CHOICE_FACILITATOR = 'facilitator'
CHOICE_ANONYMOUS = 'anonymous'
CHOICE_CONTACT = 'contact'
MEDIUM_CHOICES = [
    (CHOICE_ANONYMOUS, _('Remain anonymous')),
    (CHOICE_FACILITATOR, _('Receive updates from facilitator')),
    (CHOICE_CONTACT, _('Receive updates directly')),
]

CHOICE_EMAIL = 'email'
CHOICE_PHONE = 'phone_number'
CHOICE_SMS = 'sms'
CHOICE_WHATSAPP = 'whatsapp'
CHOICE_LETTER = 'letter'
CONTACT_CHOICES = [
    ('', ''),
    (CHOICE_EMAIL, _('email')),
    (CHOICE_PHONE, _('phone call')),
    (CHOICE_SMS, _('sms')),
    (CHOICE_WHATSAPP, 'whatsapp'),
    (CHOICE_LETTER, _('by letter (correspondence)')),
]

CHOICE_1 = 1
CHOICE_2 = 2
CHOICE_3 = 3
CITIZEN_TYPE_CHOICES = [
    (CHOICE_1, _('Keep name confidential. Only the person resolving the issue will see the name.')),
    (CHOICE_2, _('This is an individual filing on behalf of someone else.')),
    (CHOICE_3, _('This is an organization filing on behalf of someone else.')),
]

CHOICE_0_OR_1_LABEL = _('Complainant')
CITIZEN_TYPE_CHOICES_ALT = [
    (0, CHOICE_0_OR_1_LABEL),
    (CHOICE_1, CHOICE_0_OR_1_LABEL),
    (CHOICE_2, _('Citizen on behalf of others')),
    (CHOICE_3, _('Organization on behalf of others')),
]

CHOICE_MALE = "Male"
CHOICE_FEMALE = "Female"
CHOICE_OTHER = "Other"
CHOICE_RNS = "Rather not say"

GENDER_CHOICES = [
    ('', ''),
    (CHOICE_MALE, _(CHOICE_MALE)),
    (CHOICE_FEMALE, _(CHOICE_FEMALE)),
    (CHOICE_OTHER, _(CHOICE_OTHER)),
    (CHOICE_RNS, _(CHOICE_RNS)),
]

CHOICE_INDIVIDUAL = "Individual"
CHOICE_GROUP = "Group"
CITIZEN_OR_GROUP_CHOICES = [
    (CHOICE_INDIVIDUAL, _('Individual')),
    (CHOICE_GROUP, _('Group')),
]