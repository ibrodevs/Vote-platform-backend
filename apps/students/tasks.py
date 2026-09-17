import io
import csv
import openpyxl
from celery import shared_task
from django.db import transaction
from .models import Student, UploadBatch
from .services import clean_phone_number

@shared_task(bind=True)
def process_student_upload_batch(self, batch_id: str, file_content_bytes: bytes, file_name: str):
    try:
        batch = UploadBatch.objects.get(id=batch_id)
    except UploadBatch.DoesNotExist:
        return f"Batch {batch_id} not found"

    batch.status = UploadBatch.Status.PROCESSING
    batch.save(update_fields=['status'])

    errors = []
    success_count = 0
    total_rows = 0

    rows_data = []

    # Detect file type
    is_excel = file_name.lower().endswith(('.xlsx', '.xls'))

    try:
        if is_excel:
            workbook = openpyxl.load_workbook(io.BytesIO(file_content_bytes), data_only=True)
            sheet = workbook.active
            headers = []
            for idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if idx == 1:
                    headers = [str(h).strip().lower() if h is not None else '' for h in row]
                    continue
                if not any(row):
                    continue
                total_rows += 1
                row_dict = {}
                for h_idx, header_name in enumerate(headers):
                    if h_idx < len(row):
                        row_dict[header_name] = row[h_idx]
                rows_data.append((idx, row_dict))
        else:
            # CSV processing
            content = file_content_bytes.decode('utf-8-sig', errors='replace')
            reader = csv.DictReader(io.StringIO(content))
            headers = [h.strip().lower() for h in (reader.fieldnames or [])]
            for idx, row in enumerate(reader, start=2):
                if not any(row.values()):
                    continue
                total_rows += 1
                # normalize keys
                normalized_row = {k.strip().lower(): v for k, v in row.items() if k}
                rows_data.append((idx, normalized_row))
    except Exception as e:
        batch.status = UploadBatch.Status.FAILED
        batch.error_count = 1
        batch.errors_detail = [{"line": 1, "reason": f"Не удалось прочитать файл: {str(e)}"}]
        batch.save()
        return f"Failed to parse file: {str(e)}"

    batch.total_rows = total_rows
    batch.save(update_fields=['total_rows'])

    # Standard column alias mapping
    def get_val(row_dict, *keys):
        for k in keys:
            for actual_key, val in row_dict.items():
                if k in actual_key:
                    return str(val).strip() if val is not None else ''
        return ''

    for line_num, row in rows_data:
        student_id = get_val(row, 'student_id', 'номер', 'код', 'id')
        full_name = get_val(row, 'full_name', 'фио', 'name', 'имя')
        phone_raw = get_val(row, 'phone_number', 'phone', 'телефон', 'номер телефона')
        faculty = get_val(row, 'faculty', 'факультет')
        course_raw = get_val(row, 'course', 'курс')
        email = get_val(row, 'email', 'почта')

        # Validation checks
        if not student_id:
            errors.append({"line": line_num, "reason": "Отсутствует номер студенческого билета/ID студента"})
            continue
        if not full_name:
            errors.append({"line": line_num, "reason": "Отсутствует ФИО студента"})
            continue
        if not phone_raw:
            errors.append({"line": line_num, "reason": "Отсутствует номер телефона"})
            continue

        clean_phone = clean_phone_number(phone_raw)
        if len(clean_phone) < 9:
            errors.append({"line": line_num, "reason": f"Некорректный формат телефона: {phone_raw}"})
            continue

        course = 1
        if course_raw:
            try:
                course = int(float(course_raw))
                if course < 1 or course > 7:
                    course = 1
            except ValueError:
                course = 1

        try:
            with transaction.atomic():
                Student.objects.update_or_create(
                    university=batch.university,
                    student_id=student_id,
                    defaults={
                        'full_name': full_name,
                        'phone_number': clean_phone,
                        'email': email or None,
                        'faculty': faculty or 'Общий',
                        'course': course,
                        'uploaded_batch': batch,
                        'is_active': True,
                    }
                )
                success_count += 1
        except Exception as err:
            errors.append({"line": line_num, "reason": f"Ошибка сохранения: {str(err)}"})

    batch.success_count = success_count
    batch.error_count = len(errors)
    batch.errors_detail = errors
    batch.status = UploadBatch.Status.COMPLETED if (success_count > 0 or not errors) else UploadBatch.Status.FAILED
    batch.save()

    return f"Batch {batch_id} completed: {success_count} succeeded, {len(errors)} errors"
