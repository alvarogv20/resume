"""Human-readable analysis is persisted before audit and PDF export."""
from .match import fact_index
from .review import fields


def analysis_documents(profile, job, adapted, status, warnings):
    facts = fact_index(profile)
    matches = {m['requirement_id']: m for m in adapted['matches']}
    claims = list(fields(adapted))
    lines = ['# Cruce con el perfil', '', f'Estado: {status}', '',
             'Los gaps son resultados del análisis, no errores de generación.', '']
    for requirement in job['requirements']:
        match = matches[requirement['id']]
        evidence = set(match['evidence_ids'])
        lines += [f"## {requirement['id']}: {requirement['text']}",
                  f"Estado: {match['status']} · Prioridad: {requirement['priority']}",
                  f"Condición: {requirement['condition'] or 'Sin condición adicional'}",
                  f"Lógica: {requirement['logic']} · Opciones: {', '.join(requirement['options']) or 'Individual'}",
                  '', 'Evidencia del perfil:']
        lines += [f'- {facts[i]} ({i})' for i in match['evidence_ids']] or ['- Sin evidencia documentada.']
        lines += ['', 'Encaje y limitación: ' + match['rationale'], '',
                  'Textos del CV que comparten esta evidencia (relación por IDs, no prueba de causalidad editorial):']
        linked = [f"- {path}: {claim['text']}" for path, claim, _ in claims if evidence.intersection(claim['evidence_ids'])]
        lines += linked or ['- No se ha incorporado una afirmación específica al CV.']
        if match['status'] in ('gap', 'unconfirmed', 'transferable'):
            lines += ['Pendiente: revisar la limitación indicada; no se afirma cumplir la parte sin respaldo.']
        lines += ['']
    lines += ['## Advertencias', ''] + ['- ' + str(w) for w in warnings]
    decisions = ['# Decisiones editoriales', '', f'Estado: {status}', '']
    decisions += ['- ' + x for x in adapted['decisions']] or ['- Adaptación conservadora de hechos del perfil.']
    decisions += ['', '## Requisitos no afirmados como cumplidos', '']
    decisions += [f"- {r['text']}: {matches[r['id']]['rationale']}" for r in job['requirements']
                  if matches[r['id']]['status'] not in ('direct', 'not_applicable')]
    decisions += ['', '## Pendiente de confirmar', ''] + ['- ' + x for x in adapted['questions']]
    return '\n'.join(lines) + '\n', '\n'.join(decisions) + '\n'
