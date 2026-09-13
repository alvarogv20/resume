"""Reviewed-in-code Spanish presentation; source strings prevent stale translations."""
import copy

ES = {
    'Madrid, Spain': 'Madrid, España',
    'Technical Area Responsible': 'Responsable de área técnica',
    'Senior Project Engineer & Project Manager': 'Ingeniero sénior de proyectos y director de proyectos',
    'Aeroelastic Loads Engineer': 'Ingeniero de cargas aeroelásticas',
    'January 2025 - Present': 'Enero de 2025 - Actualidad',
    'June 2023 - January 2025': 'Junio de 2023 - Enero de 2025',
    'December 2021 - June 2023': 'Diciembre de 2021 - Junio de 2023',
    'Manage a 10-member Aeroelasticity & Controls team, organizing workloads and supervising R&D objectives.':
        'Gestiono un equipo de 10 personas de aeroelasticidad y control, organizando cargas de trabajo y supervisando objetivos de I+D.',
    'Coordinate customer communications and support commercial requirements.':
        'Coordino la comunicación con clientes y apoyo los requisitos comerciales.',
    'Prepare technical and commercial proposals for business development and client portfolio diversification.':
        'Preparo propuestas técnicas y comerciales para el desarrollo de negocio y la diversificación de la cartera de clientes.',
    'Led development of a rotating-wing UAV for wind turbine inspection, covering technical requirements, system architecture, certification processes and testing.':
        'Dirigí el desarrollo de un UAV de ala rotatoria para inspeccionar aerogeneradores, abarcando requisitos técnicos, arquitectura de sistemas, procesos de certificación y ensayos.',
    'Provided technical and functional coordination for wind turbine projects and engineering teams, including life extension and structural integrity.':
        'Coordiné técnica y funcionalmente proyectos de aerogeneradores y equipos de ingeniería, incluyendo extensión de vida e integridad estructural.',
    'Managed load certification processes against IEC/DNV standards for international projects.':
        'Gestioné procesos de certificación de cargas conforme a normas IEC/DNV en proyectos internacionales.',
    'Developed Python and MATLAB scripts to reduce load calculation cycle times and support wind turbine design optimization.':
        'Desarrollé scripts de Python y MATLAB para reducir los tiempos de cálculo de cargas y apoyar la optimización del diseño de aerogeneradores.',
    'Developed engineering methodologies for Dynamic Wake Meandering and floating wind turbine loads.':
        'Desarrollé metodologías de ingeniería para Dynamic Wake Meandering y cargas en aerogeneradores flotantes.',
    'Performed aeroelastic simulations and dynamic load analyses for GE Renewables offshore turbines, covering bottom-fixed and floating configurations.':
        'Realicé simulaciones aeroelásticas y análisis de cargas dinámicas para aerogeneradores marinos de GE Renewables, en configuraciones de cimentación fija y flotantes.',
    'Conducted site-specific assessments and control tuning for wind turbine projects.':
        'Realicé evaluaciones específicas de emplazamiento y ajustes de control en proyectos de aerogeneradores.',
    'Python, MATLAB, Git; engineering methodology development; simulation workflow optimization.':
        'Python, MATLAB, Git; desarrollo de metodologías de ingeniería; optimización de flujos de simulación.',
    'Aeroelasticity, structural dynamics, Bladed, HAWC2; CFD with Fluent; structural tools with NX; CAD with CATIA V5.':
        'Aeroelasticidad, dinámica estructural, Bladed, HAWC2; CFD con Fluent; herramientas estructurales con NX; CAD con CATIA V5.',
    'Team leadership, R&D supervision, customer coordination, technical requirements, system architecture, IEC/DNV load certification.':
        'Liderazgo de equipos, supervisión de I+D, coordinación con clientes, requisitos técnicos, arquitectura de sistemas y certificación de cargas IEC/DNV.',
    'MS Project, Jira, Smartsheet.': 'MS Project, Jira, Smartsheet.',
    "Master's Degree in Aeronautical Engineering | 2019 - 2021 | Universidad Politécnica de Madrid and University of Liège.":
        'Máster en Ingeniería Aeronáutica | 2019 - 2021 | Universidad Politécnica de Madrid y Universidad de Lieja.',
    "Bachelor's Degree in Aerospace Engineering | 2015 - 2019 | Universidad Politécnica de Madrid | Average 7.97/10 | Top 5% distinction.":
        'Grado en Ingeniería Aeroespacial | 2015 - 2019 | Universidad Politécnica de Madrid | Media de 7,97/10 | Distinción del 5% superior.',
    'Final project: Carbon fiber recycling using 3D printing - Honors, 9.8/10.':
        'Trabajo final: reciclaje de fibra de carbono mediante impresión 3D - Matrícula de honor, 9,8/10.',
    'Spanish: Native': 'Español: nativo',
    'English: Advanced, professional working proficiency': 'Inglés: avanzado, competencia profesional',
}


def translate(text, language):
    if language == 'en':
        return text
    if language != 'es' or text not in ES:
        raise ValueError('Missing verified presentation translation; add the exact source to localization.ES.')
    return ES[text]


def localized_profile(profile, language):
    if language == 'en':
        return profile
    result = copy.deepcopy(profile)
    result['location'] = translate(result['location'], language)
    for role in result['experience']:
        for key in ('title', 'dates', 'location'):
            role[key] = translate(role[key], language)
        for fact in role['facts']:
            fact['text'] = translate(fact['text'], language)
    for group in ('skills', 'education', 'languages'):
        for fact in result[group]:
            fact['text'] = translate(fact['text'], language)
    return result
