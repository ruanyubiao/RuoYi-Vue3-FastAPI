class Config:
    """E2E 打本机 test-* 容器 + PC 后端（python app.py --env=test）。"""

    frontend_url = 'http://localhost:18080'
    backend_url = 'http://localhost:19099'
    app_title = '激光终端地检系统'
    root_dept_name = '成都总公司'
