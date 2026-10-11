"""Election-day student read hot paths.

The election/candidate payload is shared by many students. Rebuilding it from
PostgreSQL + DRF serializers for every JWT request is wasted work during the
opening burst. This module caches only non-personal data.

`has_voted` is NEVER cached as false. Each authenticated request still checks
VoteRecord in PostgreSQL, so Redis remains an accelerator and a stale cache
cannot allow a double vote or hide an existing participation record.
"""
from copy import deepcopy

from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.candidates.models import Candidate
from apps.core.cache import safe_get, safe_set
from apps.core.cache_keys import active_elections_catalog, election_student_detail
from apps.core.cache_policy import CachePolicy
from apps.core.permissions import IsStudentAuthenticated
from apps.voting.models import VoteRecord

from .models import Election
from .serializers import ElectionStudentSerializer
from .views import StudentAvailableElectionsView


def _absolutize_candidate_media(request, rows):
    """Cached media paths are host-neutral; make them absolute per response."""
    for election in rows:
        for candidate in election.get('candidates') or ():
            photo = candidate.get('photo')
            if isinstance(photo, str) and photo.startswith('/'):
                candidate['photo'] = request.build_absolute_uri(photo)
    return rows


class StudentAvailableElectionsHotView(APIView):
    """Optimized normal `/elections/available/` path.

    `?all=true` is an account/history feature, not the election-opening hot
    path, and deliberately delegates to the original implementation.
    """

    permission_classes = [IsStudentAuthenticated]

    @staticmethod
    def _catalog(university_id):
        key = active_elections_catalog(university_id)
        cached = safe_get(key)
        if cached is not None:
            return deepcopy(cached)

        now = timezone.now()
        elections = (
            Election.objects.select_related('university')
            .prefetch_related(
                Prefetch(
                    'candidates',
                    queryset=(
                        Candidate.objects.select_related('university', 'election')
                        .order_by('order', 'created_at')
                    ),
                )
            )
            .filter(
                university_id=university_id,
                status=Election.Status.ACTIVE,
                starts_at__lte=now,
                ends_at__gte=now,
            )
            .order_by('ends_at')
        )

        # No request in context on purpose: media URLs stay relative and the
        # cached value is independent of Host. They are absolutized cheaply for
        # the current request after the cache lookup.
        data = [dict(item) for item in ElectionStudentSerializer(elections, many=True).data]
        safe_set(key, data, timeout=CachePolicy.ACTIVE_ELECTIONS_CATALOG)
        return deepcopy(data)

    def get(self, request):
        if request.query_params.get('all', 'false').lower() == 'true':
            # Preserve the existing full-history API contract outside the hot path.
            return StudentAvailableElectionsView().get(request)

        student_id = request.user.id
        university_id = request.user.university_id
        catalog = self._catalog(university_id)

        election_ids = [row.get('id') for row in catalog if row.get('id')]
        if not election_ids:
            return Response([], status=status.HTTP_200_OK)

        # One small indexed query is the ONLY PostgreSQL work unique to the
        # student. A negative result is intentionally not cached.
        voted_ids = {
            str(value)
            for value in VoteRecord.objects.filter(
                student_id=student_id,
                election_id__in=election_ids,
            ).values_list('election_id', flat=True)
        }

        available = []
        for row in catalog:
            if str(row.get('id')) in voted_ids:
                continue
            row['has_voted'] = False
            available.append(row)

        _absolutize_candidate_media(request, available)
        return Response(available, status=status.HTTP_200_OK)


class StudentElectionDetailHotView(APIView):
    """Shared detail payload + one personal VoteRecord lookup.

    The endpoint intentionally stays AllowAny for API compatibility. Anonymous
    requests are even cheaper after the first cache fill; requests carrying a
    student JWT still receive personalized `has_voted` and `is_eligible`.
    """

    permission_classes = [permissions.AllowAny]

    @staticmethod
    def _shared_detail(pk):
        key = election_student_detail(pk)
        cached = safe_get(key)
        if cached is not None:
            return deepcopy(cached)

        try:
            election = (
                Election.objects.select_related('university')
                .prefetch_related(
                    Prefetch(
                        'candidates',
                        queryset=(
                            Candidate.objects.select_related('university', 'election')
                            .order_by('order', 'created_at')
                        ),
                    )
                )
                .get(id=pk)
            )
        except Election.DoesNotExist:
            return None

        data = dict(ElectionStudentSerializer(election).data)
        safe_set(key, data, timeout=CachePolicy.ELECTION_PUBLIC)
        return deepcopy(data)

    def get(self, request, pk):
        data = self._shared_detail(pk)
        if data is None:
            return Response(
                {'error': {'code': 'not_found', 'message': 'Выборы не найдены'}},
                status=status.HTTP_404_NOT_FOUND,
            )

        is_student = getattr(request.user, 'is_student', False)
        if is_student:
            # UNIQUE(election, student) already provides the covering B-tree for
            # this existence check. Never cache the negative answer.
            data['has_voted'] = VoteRecord.objects.filter(
                election_id=pk,
                student_id=request.user.id,
            ).exists()
            data['is_eligible'] = (
                str(request.user.university_id) == str(data.get('university'))
            )
        else:
            data['has_voted'] = False
            data['is_eligible'] = None

        _absolutize_candidate_media(request, [data])
        return Response(data, status=status.HTTP_200_OK)
