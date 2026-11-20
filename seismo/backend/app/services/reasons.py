"""Причины пометки записи для ручной проверки (код → описание на русском)."""
REASON_LABELS = {
    "ocr": "Распознано OCR — проверьте значения",
    "station_mismatch": "Код станции в строке не совпадает со станцией файла",
    "near_duplicate": "Возможный дубль: то же время вступления P, но другие значения",
    "time_order": "Нарушен порядок времён (P / S / время в очаге)",
    "sp_mismatch": "S-P не согласуется с разностью времён S и P",
    "mag_range": "Магнитуда вне физически возможного диапазона",
    "amp_range": "Аномально большая амплитуда (>1000 мк/с)",
    "vel_range": "Скорость Ep Vp/Vs вне допустимого диапазона",
    "vpvs_range": "Ep Vp/Vs вне диапазона 1.5–2.1",
    "dist_range": "Расстояние более 3000 км",
    "date_outlier": "Дата резко выбивается из соседних записей листа — возможна опечатка (год/месяц)",
    "date_future": "Дата в будущем — вероятна опечатка (год)",
    "date_time_order": "Время P раньше предыдущей записи при той же дате — возможно, пропущена смена суток (дата неверна)",
    "manual": "Помечено вручную",
}
FIELD_LABELS = {
    "no": "No", "p_phase": "фаза P", "s_phase": "фаза S", "p_time": "время P", "s_time": "время S",
    "origin_time": "время в очаге", "s_minus_p": "S-P", "r_km": "R км", "amp_p": "A(P)", "amp_s": "A(S)",
    "mb": "Mb", "ml": "ML", "ep_vp": "Ep Vp", "ep_vs": "Ep Vs", "ep_vp_vs": "Ep Vp/Vs",
}


def reason_text(code: str) -> str:
    if code in REASON_LABELS:
        return REASON_LABELS[code]
    kind, _, field = code.partition(":")
    f = FIELD_LABELS.get(field, field)
    if kind == "parse":
        return f"Не удалось распознать значение: {f} (в базе NULL, исходник — в raw)"
    if kind == "excel_error":
        return f"В исходном файле ошибка Excel (#VALUE! и т.п.): {f} — значение не получено (в базе NULL)"
    if kind == "missing":
        return f"Значение отсутствует: {f}"
    return code
