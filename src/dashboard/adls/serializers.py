"""Même principe que dashboard/grm/serializers.py : reproduit la forme du document CouchDB
`adl` (base `eadls`) à partir d'une instance `issue.models.Adl` Postgres, pour que les templates
existants (`adls/list.html`, `adls/profile.html`) continuent de lire `doc.representative.name`,
`doc.administrative_regions`, `doc|get:'_id'`, etc. sans changement."""


def adl_to_legacy_dict(adl):
    representative = adl.representative
    return {
        '_id': str(adl.pk),
        'type': 'adl',
        'name': adl.name,
        'location_name': adl.location_name,
        'administrative_region': str(adl.administrative_region_ids[0]) if adl.administrative_region_ids else None,
        'administrative_regions': [str(i) for i in adl.administrative_region_ids],
        'smallest_administrative_level_ids': [str(i) for i in adl.smallest_administrative_level_ids],
        'additional_administrative_regions': [str(i) for i in adl.additional_administrative_region_ids],
        'additional_smallest_administrative_level_ids': [str(i) for i in adl.additional_smallest_administrative_level_ids],
        'representative': ({
            'id': representative.id,
            'name': representative.name,
            'email': representative.email,
            'phone': representative.phone_number,
            'photo': representative.photo.url if representative.photo else '',
            'is_active': representative.is_active,
        } if representative else None),
    }
