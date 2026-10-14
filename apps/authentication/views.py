from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class UsuarioLogadoView(APIView):
    """Confere o token e devolve os dados do usuário autenticado."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        usuario = request.user
        return Response(
            {
                'id': usuario.pk,
                'username': usuario.username,
                'email': usuario.email,
                'nome': usuario.get_full_name(),
            }
        )