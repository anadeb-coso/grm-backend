import factory
from django.utils import timezone

tzinfo = timezone.get_current_timezone()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = 'authentication.User'

    email = factory.Faker('email')
    phone_number = factory.Faker('phone_number')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    is_active = True


class GovernmentWorkerFactory(factory.django.DjangoModelFactory):
    """Rattaché à un `User` pour que `User.administrative_level` (utilisé par
    `authentication.serializers.RegisterSerializer`) résolve à une valeur non nulle."""
    class Meta:
        model = 'authentication.GovernmentWorker'

    user = factory.SubFactory(UserFactory)
    department = 1
    administrative_id = '1'


class AdlFactory(factory.django.DjangoModelFactory):
    """`issue.models.Adl` (remplace l'ancienne fabrique CouchDB `CouchdbUserFactory`/
    `CouchdbADLFactory`/`CouchdbMajorFactory` — la distinction de type `adl`/`major`/`commune` du
    document CouchDB `eadls` n'a pas d'équivalent Postgres, cf. authentication/serializers.py).
    `get_or_create` sur `representative` : la création du `User` déclenche déjà le signal
    `authentication.utils.create_or_update_adl_user_adl`, qui crée l'`Adl` correspondant — cette
    fabrique met alors à jour cet enregistrement plutôt que d'en créer un second."""
    class Meta:
        model = 'issue.Adl'
        django_get_or_create = ('representative',)

    name = factory.Faker('name')
    representative = factory.SubFactory(UserFactory)
    representative_name = factory.SelfAttribute('representative.name')
    administrative_region_ids = factory.LazyFunction(list)


class PhaseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = 'budgeting.Phase'

    adl = factory.SubFactory(AdlFactory)
    ordinal = 1
    title = factory.Faker('sentence')


class TaskFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = 'budgeting.Task'

    phase = factory.SubFactory(PhaseFactory)
    ordinal = 1
    title = factory.Faker('sentence')


class IssueFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = 'issue.Issue'

    internal_code = factory.Sequence(lambda n: f'TEST-ISSUE-{n}')
    auto_increment_id = factory.Sequence(lambda n: n)
    description = factory.Faker('text')
    created_date = factory.LazyFunction(timezone.now)
    intake_date = factory.LazyFunction(timezone.now)
    issue_date = factory.LazyFunction(timezone.now)
