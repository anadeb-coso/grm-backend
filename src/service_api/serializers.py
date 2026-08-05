from rest_framework import serializers

from issue.models import Issue, IssueCategory, IssueStatus


class IssueCategoryServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = IssueCategory
        fields = ['legacy_id', 'name', 'label', 'abbreviation', 'confidentiality_level', 'administrative_level']


class IssueStatusServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = IssueStatus
        fields = [
            'legacy_id', 'name', 'final_status', 'initial_status', 'rejected_status',
            'open_status', 'unresolved_status', 'eligible_status', 'not_eligible_status',
        ]


class _LightUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    name = serializers.CharField()


class IssueServiceSerializer(serializers.ModelSerializer):
    """Vue allégée d'une `Issue`, pour les écrans de recherche/statistiques externes (MIS
    `administrativelevels/grm/`) — remplace les requêtes Mango CouchDB `type: 'issue'`."""
    status = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    assignee = _LightUserSerializer(allow_null=True)
    reporter = _LightUserSerializer(allow_null=True)
    administrative_region_id = serializers.IntegerField()

    class Meta:
        model = Issue
        fields = [
            'id', 'auto_increment_id', 'internal_code', 'tracking_code', 'description',
            'confirmed', 'publish', 'status', 'category', 'administrative_region_id',
            'assignee', 'reporter', 'created_date', 'intake_date', 'issue_date',
            'resolution_date',
        ]

    def get_status(self, issue):
        if not issue.status_id:
            return None
        return {'id': issue.status.legacy_id, 'name': issue.status.name}

    def get_category(self, issue):
        if not issue.category_id:
            return None
        return {'id': issue.category.legacy_id, 'name': issue.category.name}
