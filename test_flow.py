import sys
sys.path.append('C:/Users/diana/.gemini/antigravity/scratch/bidengine-v3_7-metodo-metal/src')
from bidkit.alkan_method import ProjectEstimate, calculate_preestimate, apply_contractor_adjustment, finalize_project_estimate

# Crear preestimado simple
proj = ProjectEstimate(
    project_id='demo1',
    name='Demo Project',
    status='preestimado',
    scope_items=[],
    materials=[],
    preliminary_hours=100,
    county='unknown',
    is_prevailing_wage=False,
    distance_miles=10,
    client_type='owner',
    supplier_quotes_used=False,
    confirmed_hours=None,
    contractor_markup_pct=None,
    final_price=None,
    needs_quote_items=[]
)
print('Preestimate created:', proj)
# Aplicar ajuste de contratista
proj = apply_contractor_adjustment(proj, confirmed_hours=120, contractor_markup=0.10)
print('After contractor adjustment:', proj)
# Finalizar proyecto
proj = finalize_project_estimate(proj)
print('Final project:', proj)
