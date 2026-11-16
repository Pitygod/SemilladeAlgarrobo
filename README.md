
## Inicio rápido

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Linux/Mac: cp .env.example .env  → completar valores
python manage.py migrate
python manage.py runserver
```

- Sitio: <http://127.0.0.1:8000/>
- Ingreso / registro: <http://127.0.0.1:8000/ingresar/>
- Administración: <http://127.0.0.1:8000/admin/>

```
Cuentas:

Usuario:
admin@comunidades.org
admin2026

inti@comunidad.org
facu2026
