"""Explicit read-only live smoke test: python -m app.check_canvas.

Never downloads a file or persists course data. Output contains only counts.
"""

from app.core.config import Settings
from app.services.canvas_errors import CanvasError
from app.services.canvas_service import CanvasService


def main() -> int:
    settings = Settings()
    if not settings.canvas_base_url.strip() or not settings.canvas_access_token.get_secret_value().strip():
        print("Real Canvas integration not verified: credentials are not configured.")
        return 2
    try:
        with CanvasService(settings) as service:
            service.check_connection()
            courses = service.get_courses()
            print(f"Connection verified; courses read: {len(courses)}")
            # Bound discovery; report incomplete coverage rather than assuming success.
            module_count = item_count = 0
            for course in courses[:3]:
                modules = service.get_modules(course.canvas_course_id)
                module_count += len(modules)
                for module in modules[:5]:
                    items = service.get_module_items(course.canvas_course_id, module.module_id)
                    item_count += len(items)
                    for item in items:
                        if item.canvas_file_id is not None:
                            service.get_file(item.canvas_file_id)
                            print(f"Modules read: {module_count}; items read: {item_count}; file metadata verified.")
                            return 0
            print(f"Modules read: {module_count}; items read: {item_count}.")
            print("File metadata not verified: no accessible File item found within the bounded sample.")
            return 2
    except CanvasError as error:
        print(f"Canvas check failed [{error.code}]: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
