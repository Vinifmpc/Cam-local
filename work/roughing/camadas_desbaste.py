"""Referência parcial do planejamento de camadas observado no MeshCAM 9.

Somente profundidades; não calcula trajetórias, colisões ou G-code.
Entradas em milímetros. A validação abaixo pertence a esta implementação,
não é uma reprodução do comportamento do executável para entradas inválidas.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Camada:
    z: float
    passo: float
    margem_amostragem: float
    tolerancia: float


def planejar_camadas(z_min_modelo: float, z_min_limite: float,
                    z_max_limite: float, stepdown: float,
                    tolerancia: float = 0.0) -> list[Camada]:
    """Distribui uniformemente o intervalo, respeitando o stepdown máximo.

    O fundo efetivo é max(z_min_modelo, z_min_limite) + tolerancia.
    O topo é z_max_limite, inclusive quando o topo do modelo é diferente.
    A margem de amostragem é um argumento interno da rotina por camada;
    sua semântica geométrica completa ainda não está validada.
    """
    values = (z_min_modelo, z_min_limite, z_max_limite, stepdown, tolerancia)
    if not all(math.isfinite(value) for value in values):
        raise ValueError('As entradas devem ser finitas.')
    if stepdown <= 0 or tolerancia < 0:
        raise ValueError('Stepdown deve ser positivo e tolerância não negativa.')
    fundo = max(z_min_modelo, z_min_limite) + tolerancia
    intervalo = z_max_limite - fundo
    if intervalo <= 0:
        raise ValueError('O topo deve ficar acima do fundo efetivo.')
    quantidade = math.ceil(intervalo / stepdown)
    if quantidade > 100_000:
        raise ValueError('Limite desta referência: 100.000 camadas.')
    passo = intervalo / quantidade
    return [Camada(max(fundo, z_max_limite - (indice + 1) * passo),
                   passo, passo + tolerancia * 10, tolerancia)
            for indice in range(quantidade)]


if __name__ == '__main__':
    import json
    from dataclasses import asdict
    print(json.dumps([asdict(camada) for camada in
                      planejar_camadas(0, -1, 10, 3)], indent=2))
