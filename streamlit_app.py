# ==========================================
    # Furnace Detection Logic (แก้ไขใหม่)
    # ==========================================
    # เอาชื่อไฟล์ (filename) มารวมกับข้อความที่แกะได้จากไฟล์ เพื่อให้ค้นหาเจอคำว่า EVO, M2 ฯลฯ
    recipe_corpus = f"{filename} " + " ".join([clean_paq_text(s) for s in raw_texts])
    
    furnace_id, furnace_variant = "NB3", "NB3"
    
    # สลับลำดับให้โมเดลเฉพาะเจาะจง (EVO, M2, KE8) อยู่ด้านบนก่อน
    if re.search(r'\b(KE8|M2|EVO)\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB3", "NB3 (KE8 : M2/EVO)"
    elif re.search(r'\bRAD\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB1", "NB1 (RAD)"
    elif re.search(r'\b(CDS|KN9|12SHP)\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB1", "NB1 (CDS/KN9/12SHP)"
    elif re.search(r'\bBTM\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB3", "NB3 (BTM)"
    elif re.search(r'\b(Utahc|UT)\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB2", "NB2 (Utahc)"
    elif re.search(r'\b(Tahc|G2|NB2)\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB2", "NB2 (Tahc)"
    elif re.search(r'\bNB3\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB3", "NB3"
    elif re.search(r'\bWK\d{1,2}\b', recipe_corpus, re.IGNORECASE): 
        furnace_id, furnace_variant = "NB1", "NB1 (Standard)"
    else:
        f_match = re.search(r'NB\s*Furnace\s*0?([123])\b|NB-0?([123])\b', recipe_corpus, re.IGNORECASE)
        if f_match: 
            found_num = next(g for g in f_match.groups() if g is not None)
            furnace_id = furnace_variant = f"NB{found_num}"
