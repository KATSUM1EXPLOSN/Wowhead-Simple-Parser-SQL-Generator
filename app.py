import streamlit as st
import re
import requests
from bs4 import BeautifulSoup

# --- КОНФИГУРАЦИЯ ---
ST_PAGE_TITLE = "Wowhead Simple Parser"
WOWHEAD_URL = "https://www.wowhead.com"
ICON_URL_BASE = "https://wow.zamimg.com/images/wow/icons/large/{}.jpg"

# Настройка страницы Streamlit
st.set_page_config(page_title=ST_PAGE_TITLE, page_icon="⚔️")

def format_money(copper):
    """Форматирует медь в строку вида 1g 50s 20c."""
    if not copper: return "0c"
    try:
        copper = int(copper)
        g = copper // 10000
        s = (copper % 10000) // 100
        c = copper % 100
        return f"{g}g {s}s {c}c" if g > 0 else f"{s}s {c}c"
    except:
        return "0c"

# --- ФУНКЦИИ ---

def fetch_wowhead_data(item_id, lang='ru', version='', proxies=None):
    """
    Получает данные о предмете с Wowhead через XML интерфейс.
    """
    # Wowhead поддерживает &xml для получения структурированных данных
    domain = "ru.wowhead.com" if lang == 'ru' else "www.wowhead.com"
    prefix = f"{version}/" if version else ""
    url = f"https://{domain}/{prefix}item={item_id}&xml"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers, proxies=proxies, timeout=10)
        response.raise_for_status()

        # Парсим XML (используем xml features для корректной работы с тегами)
        soup = BeautifulSoup(response.content, 'xml')

        # Проверяем, вернул ли Wowhead ошибку (пустой item)
        if not soup.find('item'):
            return None, "Предмет не найден или ID неверен."

        item = soup.find('item')

        # Дополнительные данные для TrinityCore
        inventory_slot = item.find('inventorySlot')

        data = {
            'id': item.get('id'),
            'name': item.find('name').text,
            'level': item.find('level').text,
            'quality': item.find('quality').get('id'), # 0-5 (серый, белый, зеленый...)
            'icon': item.find('icon').text,
            'display_id': item.find('icon').get('displayId') or '0',
            'link': item.find('link').text,
            'class': item.find('class').text,
            'class_id': item.find('class').get('id'),
            'subclass': item.find('subclass').text,
            'subclass_id': item.find('subclass').get('id'),
            'inventory_type': inventory_slot.get('id') if inventory_slot else '0'
        }
        return data, None

    except requests.exceptions.RequestException as e:
        return None, f"Ошибка сети: {e}"
    except Exception as e:
        return None, f"Ошибка парсинга: {e}"

def fetch_npc_data(npc_id, lang='ru', version='', proxies=None):
    """Получает данные NPC (статы + лут) с Wowhead."""
    domain = "ru.wowhead.com" if lang == 'ru' else "www.wowhead.com"
    prefix = f"{version}/" if version else ""
    url = f"https://{domain}/{prefix}npc={npc_id}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers, proxies=proxies, timeout=10)
        response.raise_for_status()

        # Для NPC используем HTML парсинг (lxml), так как XML API беден на лут
        soup = BeautifulSoup(response.content, 'lxml')

        # Имя NPC
        h1 = soup.find('h1', class_='heading-size-1')
        npc_name = h1.text.strip() if h1 else f"NPC {npc_id}"

        # 1. Subname (Под-имя, например <Blacksmithing Trainer>)
        subname = ""
        subname_tag = soup.find('span', class_='text-secondary')
        if subname_tag:
            subname = subname_tag.text.strip().replace("<", "").replace(">", "")

        # 2. Display ID (Модель)
        display_id = "0"
        for script in soup.find_all('script'):
            if script.string and "new ModelViewer" in script.string:
                m = re.search(r"displayId:\s*(\d+)", script.string)
                if m:
                    display_id = m.group(1)
                    break

        # 3. Stats (Быстрый парсинг текста страницы)
        text_content = soup.get_text()

        min_level = "0"
        max_level = "0"
        rank = "0" # 0: Normal, 1: Elite, 2: Rare Elite, 3: Boss, 4: Rare
        health = "0"
        mana = "0"

        # Level
        lvl_match = re.search(r"(Level|Уровень):\s*(\d+)(\s*-\s*(\d+))?", text_content)
        if lvl_match:
            min_level = lvl_match.group(2)
            max_level = lvl_match.group(4) if lvl_match.group(4) else min_level

        # Rank
        if "Classification: Elite" in text_content or "Классификация: Элита" in text_content: rank = "1"
        elif "Classification: Rare Elite" in text_content or "Классификация: Редкая элита" in text_content: rank = "2"
        elif "Classification: Boss" in text_content or "Классификация: Босс" in text_content: rank = "3"
        elif "Classification: Rare" in text_content or "Классификация: Редкий" in text_content: rank = "4"

        # Health & Mana
        health_match = re.search(r"(Health|Здоровье):\s*([\d,\.\s]+)", text_content)
        if health_match: health = health_match.group(2).replace(",", "").replace(".", "").replace("\xa0", "").strip()

        mana_match = re.search(r"(Mana|Мана):\s*([\d,\.\s]+)", text_content)
        if mana_match: mana = mana_match.group(2).replace(",", "").replace(".", "").replace("\xa0", "").strip()

        # Поиск данных о луте в скриптах (ищем блок id: 'drops')
        loot_data_text = ""
        for script in soup.find_all('script'):
            if not script.string: continue

            if "new Listview" in script.string and "id: 'drops'" in script.string:
                # Разбиваем скрипт на отдельные Listview (их может быть несколько: drops, herbing, mining...)
                listviews = script.string.split('new Listview')

                for lv in listviews:
                    if "id: 'drops'" in lv:
                        # Ищем начало массива данных data: [
                        data_match = re.search(r"data:\s*\[", lv)
                        if data_match:
                            start_idx = data_match.end() - 1 # Индекс открывающей скобки [

                            # Считаем баланс скобок, чтобы захватить весь массив корректно (с учетом вложенных stack: [1,2])
                            balance = 0
                            for i, char in enumerate(lv[start_idx:], start_idx):
                                if char == '[':
                                    balance += 1
                                elif char == ']':
                                    balance -= 1
                                    if balance == 0:
                                        loot_data_text = lv[start_idx:i+1]
                                        break
                        if loot_data_text: break
            if loot_data_text: break

        # Парсинг JS объекта. Ключи могут быть без кавычек, поэтому используем regex.
        items = []

        if loot_data_text:
            # Ручной разбор строки на объекты {...}, чтобы корректно обработать вложенные структуры (например, modes: { ... })
            raw_objects = []
            brace_level = 0
            current_obj_chars = []

            # Убираем внешние скобки [ и ]
            clean_content = loot_data_text.strip()
            if clean_content.startswith('[') and clean_content.endswith(']'):
                clean_content = clean_content[1:-1]

            for char in clean_content:
                if char == '{':
                    if brace_level == 0:
                        current_obj_chars = []
                    brace_level += 1
                    current_obj_chars.append(char)
                elif char == '}':
                    brace_level -= 1
                    current_obj_chars.append(char)
                    if brace_level == 0:
                        raw_objects.append("".join(current_obj_chars))
                elif brace_level > 0:
                    current_obj_chars.append(char)

            for raw in raw_objects:
                # Извлекаем ID (с учетом возможных кавычек у ключа "id")
                id_match = re.search(r'["\']?id["\']?\s*:\s*(\d+)', raw)
                if not id_match: continue
                item_id = id_match.group(1)

                # Извлекаем Имя
                name_match = re.search(r'["\']?name["\']?\s*:\s*["\'](.*?)["\']', raw)
                name = "Unknown"
                if name_match:
                    # Декодируем unicode-последовательности (например, \u041c)
                    try:
                        name = name_match.group(1).encode('raw_unicode_escape').decode('unicode_escape')
                    except Exception:
                        name = name_match.group(1) # Оставляем как есть в случае ошибки

                # Шанс дропа. Пробуем pctstack, если нет — считаем через count/outof
                chance = 0.0
                pct_match = re.search(r'["\']?pctstack["\']?\s*:\s*["\']?\{?\[?([\d\.]+)', raw)
                if pct_match:
                    chance = float(pct_match.group(1))
                else:
                    count_match = re.search(r'["\']?count["\']?\s*:\s*(\d+)', raw)
                    outof_match = re.search(r'["\']?outof["\']?\s*:\s*(\d+)', raw)
                    if count_match and outof_match:
                        try:
                            c = float(count_match.group(1))
                            o = float(outof_match.group(1))
                            if o > 0: chance = round((c / o) * 100, 3)
                        except: pass

                # Количество (stack: [min, max])
                stack_match = re.search(r'["\']?stack["\']?\s*:\s*\[(\d+),\s*(\d+)\]', raw)
                min_c = stack_match.group(1) if stack_match else '1'
                max_c = stack_match.group(2) if stack_match else '1'

                items.append({'id': item_id, 'name': name, 'chance': chance, 'min': min_c, 'max': max_c})

        return {
            'id': npc_id, 'name': npc_name, 'subname': subname,
            'min_level': min_level, 'max_level': max_level,
            'rank': rank, 'health': health, 'mana': mana,
            'display_id': display_id,
            'loot': items
        }, None

    except Exception as e:
        return None, f"Ошибка при загрузке NPC: {e}"

def fetch_object_loot(obj_id, lang='ru', version='', proxies=None):
    """Получает таблицу лута игрового объекта с Wowhead (парсинг JS)."""
    domain = "ru.wowhead.com" if lang == 'ru' else "www.wowhead.com"
    prefix = f"{version}/" if version else ""
    url = f"https://{domain}/{prefix}object={obj_id}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers, proxies=proxies, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'lxml')

        # Имя объекта
        h1 = soup.find('h1', class_='heading-size-1')
        obj_name = h1.text.strip() if h1 else f"Object {obj_id}"

        # Поиск данных о луте. У объектов таблицы могут называться по-разному (contains, mining, herbalism).
        loot_data_text = ""
        target_ids = ["id: 'contains'", "id: 'mining'", "id: 'herbalism'", "id: 'drops'"]

        for script in soup.find_all('script'):
            if not script.string: continue

            if "new Listview" in script.string:
                # Разбиваем скрипт на отдельные Listview
                listviews = script.string.split('new Listview')

                for lv in listviews:
                    if any(tid in lv for tid in target_ids):
                        # Ищем начало массива данных data: [
                        data_match = re.search(r"data:\s*\[", lv)
                        if data_match:
                            start_idx = data_match.end() - 1 # Индекс открывающей скобки [

                            # Считаем баланс скобок
                            balance = 0
                            for i, char in enumerate(lv[start_idx:], start_idx):
                                if char == '[':
                                    balance += 1
                                elif char == ']':
                                    balance -= 1
                                    if balance == 0:
                                        loot_data_text = lv[start_idx:i+1]
                                        break
                        if loot_data_text: break
            if loot_data_text: break

        if not loot_data_text:
            return None, "Данные о луте не найдены (возможно, объект пуст)."

        items = []

        # Ручной разбор строки на объекты {...}
        # Это необходимо, так как внутри могут быть вложенные структуры (stack: [1,2], modes: {...})
        raw_objects = []
        brace_level = 0
        current_obj_chars = []

        # Убираем внешние скобки [ и ]
        clean_content = loot_data_text.strip()
        if clean_content.startswith('[') and clean_content.endswith(']'):
            clean_content = clean_content[1:-1]

        for char in clean_content:
            if char == '{':
                if brace_level == 0:
                    current_obj_chars = []
                brace_level += 1
                current_obj_chars.append(char)
            elif char == '}':
                brace_level -= 1
                current_obj_chars.append(char)
                if brace_level == 0:
                    raw_objects.append("".join(current_obj_chars))
            elif brace_level > 0:
                current_obj_chars.append(char)

        for raw in raw_objects:
            # Извлекаем ID
            id_match = re.search(r'["\']?id["\']?\s*:\s*(\d+)', raw)
            if not id_match: continue
            item_id = id_match.group(1)

            # Извлекаем Имя
            name_match = re.search(r'["\']?name["\']?\s*:\s*["\'](.*?)["\']', raw)
            name = "Unknown"
            if name_match:
                try:
                    name = name_match.group(1).encode('raw_unicode_escape').decode('unicode_escape')
                except Exception:
                    name = name_match.group(1)

            # Шанс дропа
            chance = 0.0
            pct_match = re.search(r'["\']?pctstack["\']?\s*:\s*["\']?\{?\[?([\d\.]+)', raw)
            if pct_match:
                chance = float(pct_match.group(1))
            else:
                count_match = re.search(r'["\']?count["\']?\s*:\s*(\d+)', raw)
                outof_match = re.search(r'["\']?outof["\']?\s*:\s*(\d+)', raw)
                if count_match and outof_match:
                    try:
                        c = float(count_match.group(1))
                        o = float(outof_match.group(1))
                        if o > 0: chance = round((c / o) * 100, 3)
                    except: pass

            # Количество
            stack_match = re.search(r'["\']?stack["\']?\s*:\s*\[(\d+),\s*(\d+)\]', raw)
            min_c = stack_match.group(1) if stack_match else '1'
            max_c = stack_match.group(2) if stack_match else '1'

            items.append({'id': item_id, 'name': name, 'chance': chance, 'min': min_c, 'max': max_c})

        return {'id': obj_id, 'name': obj_name, 'loot': items}, None

    except Exception as e:
        return None, f"Ошибка при загрузке объекта: {e}"

def fetch_quest_data(quest_id, lang='ru', version='', proxies=None):
    """Получает данные о квесте с Wowhead через HTML парсинг."""
    domain = "ru.wowhead.com" if lang == 'ru' else "www.wowhead.com"
    prefix = f"{version}/" if version else ""
    url = f"https://{domain}/{prefix}quest={quest_id}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers, proxies=proxies, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'lxml')

        # Проверка названия (если нет h1, вероятно, страница ошибки)
        h1 = soup.find('h1', class_='heading-size-1')
        if not h1:
            return None, "Квест не найден (страница не содержит заголовка)."

        quest_name = h1.text.strip()

        # Парсинг уровней из тултипа или инфобокса
        # Обычно строка вида: "Уровень: 30 Требуется: 25"
        # Ищем в блоке с классом 'noscript-quest-quick-facts' или похожем, но надежнее через JS g_quests

        level = "0"
        req_level = "0"
        rewards = {'items': [], 'choice_items': [], 'xp': '0', 'money': '0'}
        req_kills = []
        req_items = []

        # Цепочка квестов (Series)
        prev_quest_id = "0"
        next_quest_id = "0"

        series_text = ""
        target_series = "id: 'quest-series'"

        for script in soup.find_all('script'):
            if not script.string: continue
            if "new Listview" in script.string and target_series in script.string:
                listviews = script.string.split('new Listview')
                for lv in listviews:
                    if target_series in lv:
                        data_match = re.search(r"data:\s*\[", lv)
                        if data_match:
                            start_idx = data_match.end() - 1
                            balance = 0
                            for i, char in enumerate(lv[start_idx:], start_idx):
                                if char == '[': balance += 1
                                elif char == ']':
                                    balance -= 1
                                    if balance == 0:
                                        series_text = lv[start_idx:i+1]
                                        break
                        if series_text: break
            if series_text: break

        if series_text:
            # Простой парсинг ID из списка
            chain_ids = re.findall(r'["\']?id["\']?\s*:\s*(\d+)', series_text)
            # Ищем индекс текущего квеста
            try:
                curr_idx = chain_ids.index(str(quest_id))
                if curr_idx > 0:
                    prev_quest_id = chain_ids[curr_idx - 1]
                if curr_idx < len(chain_ids) - 1:
                    next_quest_id = chain_ids[curr_idx + 1]
            except ValueError:
                pass

        def parse_js_objects_robust(text_content):
            """Надежный парсер JS объектов с учетом вложенных скобок."""
            objs = []
            brace_level = 0
            current_obj = []
            clean = text_content.strip()
            if clean.startswith('[') and clean.endswith(']'):
                clean = clean[1:-1]

            for char in clean:
                if char == '{':
                    if brace_level == 0: current_obj = []
                    brace_level += 1
                    current_obj.append(char)
                elif char == '}':
                    brace_level -= 1
                    current_obj.append(char)
                    if brace_level == 0:
                        objs.append("".join(current_obj))
                elif brace_level > 0:
                    current_obj.append(char)
            return objs

        # Парсинг требований (Objectives - Kill/Interact, Req - Items)
        # Ищем Listview id: 'objectives' (NPC/GO) и id: 'req' (Items)
        for script in soup.find_all('script'):
            if not script.string: continue
            if "new Listview" in script.string:
                listviews = script.string.split('new Listview')
                for lv in listviews:
                    # Required Items (Требуемые предметы)
                    if "id: 'req'" in lv:
                        data_match = re.search(r"data:\s*\[", lv)
                        if data_match:
                            start = data_match.end() - 1
                            bal = 0
                            content = ""
                            for i, c in enumerate(lv[start:], start):
                                if c == '[': bal += 1
                                elif c == ']':
                                    bal -= 1
                                    if bal == 0:
                                        content = lv[start:i+1]
                                        break
                            if content:
                                # Парсим объекты {id: 123, count: 5}
                                objs = parse_js_objects_robust(content)
                                for o in objs:
                                    id_m = re.search(r'["\']?id["\']?\s*:\s*(\d+)', o)
                                    count_m = re.search(r'["\']?count["\']?\s*:\s*(\d+)', o)
                                    if id_m:
                                        cnt = count_m.group(1) if count_m else "1"
                                        req_items.append({'id': id_m.group(1), 'count': cnt})

                    # Objectives (NPCs / GameObjects)
                    if "id: 'objectives'" in lv:
                        data_match = re.search(r"data:\s*\[", lv)
                        if data_match:
                            start = data_match.end() - 1
                            bal = 0
                            content = ""
                            for i, c in enumerate(lv[start:], start):
                                if c == '[': bal += 1
                                elif c == ']':
                                    bal -= 1
                                    if bal == 0:
                                        content = lv[start:i+1]
                                        break
                            if content:
                                objs = parse_js_objects_robust(content)
                                for o in objs:
                                    id_m = re.search(r'["\']?id["\']?\s*:\s*(\d+)', o)
                                    if not id_m: continue

                                    count_m = re.search(r'["\']?count["\']?\s*:\s*(\d+)', o)
                                    cnt = count_m.group(1) if count_m else "0"

                                    # Определяем тип: 1=NPC, 2=GameObject (Interact)
                                    # В TrinityCore объекты имеют отрицательный ID в RequiredNpcOrGo
                                    type_m = re.search(r'["\']?type["\']?\s*:\s*(\d+)', o)
                                    obj_id = id_m.group(1)

                                    # Эвристика: если type=2, считаем что это GameObject
                                    if type_m and type_m.group(1) == '2':
                                        obj_id = f"-{obj_id}"

                                    req_kills.append({'id': obj_id, 'count': cnt})

        # Поиск основных данных в JS (g_quests)
        for script in soup.find_all('script'):
            if not script.string: continue
            if f"g_quests[{quest_id}]" in script.string:
                # level
                lvl_match = re.search(r'["\']?level["\']?\s*:\s*(\d+)', script.string)
                if lvl_match: level = lvl_match.group(1)
                # reqlevel
                reql_match = re.search(r'["\']?reqlevel["\']?\s*:\s*(\d+)', script.string)
                if reql_match: req_level = reql_match.group(1)
                # money
                money_match = re.search(r'["\']?money["\']?\s*:\s*(\d+)', script.string)
                if money_match: rewards['money'] = money_match.group(1)
                # xp
                xp_match = re.search(r'["\']?xp["\']?\s*:\s*(\d+)', script.string)
                if xp_match: rewards['xp'] = xp_match.group(1)

                # Fallback: поиск наград в g_quests, если Listview не найден или пуст
                if not rewards['items']:
                    ir_match = re.search(r'["\']?itemrewards["\']?\s*:\s*(\[.*?\])', script.string, re.DOTALL)
                    if ir_match:
                        items_raw = re.findall(r'\[\s*(\d+)\s*,\s*(\d+)\s*\]', ir_match.group(1))
                        for i_id, i_cnt in items_raw:
                            rewards['items'].append({'id': i_id, 'count': i_cnt})

                if not rewards['choice_items']:
                    ic_match = re.search(r'["\']?itemchoices["\']?\s*:\s*(\[.*?\])', script.string, re.DOTALL)
                    if ic_match:
                        items_raw = re.findall(r'\[\s*(\d+)\s*,\s*(\d+)\s*\]', ic_match.group(1))
                        for i_id, i_cnt in items_raw:
                            rewards['choice_items'].append({'id': i_id, 'count': i_cnt})

            # Поиск предметов-наград в Listview (item-rewards, item-choice-rewards)
            if "new Listview" in script.string:
                listviews = script.string.split('new Listview')
                for lv in listviews:
                    is_fixed = re.search(r"id:\s*['\"]item-rewards['\"]", lv)
                    is_choice = re.search(r"id:\s*['\"]item-choice-rewards['\"]", lv)

                    if is_fixed or is_choice:
                        data_match = re.search(r"data:\s*\[", lv)
                        if data_match:
                            start_idx = data_match.end() - 1
                            balance = 0
                            lv_data_text = ""
                            for i, char in enumerate(lv[start_idx:], start_idx):
                                if char == '[': balance += 1
                                elif char == ']':
                                    balance -= 1
                                    if balance == 0:
                                        lv_data_text = lv[start_idx:i+1]
                                        break

                            if lv_data_text:
                                raw_objects = parse_js_objects_robust(lv_data_text)
                                for raw in raw_objects:
                                    id_m = re.search(r'["\']?id["\']?\s*:\s*(\d+)', raw)
                                    count_m = re.search(r'["\']?stack["\']?\s*:\s*\[(\d+)', raw)
                                    if not count_m:
                                         count_m = re.search(r'["\']?count["\']?\s*:\s*(\d+)', raw)

                                    if id_m:
                                        item_id = id_m.group(1)
                                        target_list = rewards['items'] if is_fixed else rewards['choice_items']
                                        # Проверка на дубликаты
                                        if not any(i['id'] == item_id for i in target_list):
                                            item_data = {
                                                'id': item_id,
                                                'count': count_m.group(1) if count_m else '1'
                                            }
                                            target_list.append(item_data)

        # Поиск Денег и Опыта в HTML (Quick Facts)
        for li in soup.find_all('li'):
            text = li.get_text(strip=True)
            if text.startswith("Money:") or text.startswith("Деньги:"):
                g = li.find('span', class_='moneygold')
                s = li.find('span', class_='moneysilver')
                c = li.find('span', class_='moneycopper')
                val = 0
                if g: val += int(g.text) * 10000
                if s: val += int(s.text) * 100
                if c: val += int(c.text)
                if rewards['money'] == '0':
                    rewards['money'] = str(val)
            elif text.startswith("Experience:") or text.startswith("Опыт:"):
                # Удаляем заголовок и берем число (с учетом запятых/пробелов)
                clean_text = text.replace("Experience:", "").replace("Опыт:", "").strip()
                match = re.search(r'([\d\s,]+)', clean_text)
                if match and rewards['xp'] == '0':
                    rewards['xp'] = match.group(1).replace(',', '').replace(' ', '').strip()

        # Описание и цели (обычно в div.text)
        # Структура: h2(Цели) -> text -> h2(Описание) -> text
        objectives = ""
        description = ""
        completion = ""

        def get_text_content(soup, markers):
            """Надежный поиск текста после заголовка."""
            for header in soup.find_all(['h2', 'h3', 'h4']):
                h_text = header.get_text(strip=True)
                if not any(m in h_text for m in markers):
                    continue

                content = []
                curr = header.next_sibling
                while curr:
                    # Если встретили следующий заголовок, останавливаемся
                    if curr.name in ['h1', 'h2', 'h3', 'h4']:
                        break

                    if isinstance(curr, str):
                        txt = curr.strip()
                        if txt: content.append(txt)
                    elif curr.name == 'br':
                        content.append('\n')
                    elif hasattr(curr, 'get_text') and curr.name not in ['script', 'style']:
                        txt = curr.get_text(" ", strip=True)
                        if txt: content.append(txt)

                    curr = curr.next_sibling

                if content:
                    return " ".join(content).replace('  ', ' ').strip()
            return ""

        objectives = get_text_content(soup, ["Цели", "Objectives"])
        description = get_text_content(soup, ["Описание", "Description"])
        completion = get_text_content(soup, ["Прогресс", "Progress", "Завершение", "Completion"])

        data = {
            'id': quest_id,
            'name': quest_name,
            'level': level,
            'reqLevel': req_level,
            'objectives': objectives,
            'description': description,
            'completion': completion,
            'rewards': rewards,
            'req_kills': req_kills,
            'req_items': req_items,
            'prev_quest': prev_quest_id,
            'next_quest': next_quest_id
        }
        return data, None

    except Exception as e:
        return None, f"Ошибка парсинга квеста: {e}"

def get_quality_color(quality_id):
    """Возвращает CSS цвет для качества предмета."""
    colors = {
        '0': '#9d9d9d', # Poor
        '1': '#ffffff', # Common
        '2': '#1eff00', # Uncommon
        '3': '#0070dd', # Rare
        '4': '#a335ee', # Epic
        '5': '#ff8000', # Legendary
        '6': '#e6cc80', # Artifact
        '7': '#00ccff', # Heirloom
    }
    return colors.get(str(quality_id), '#ffffff')

def generate_trinity_sql(data):
    """Генерирует SQL запрос для TrinityCore (World DB)."""
    # Экранирование кавычек в имени
    safe_name = data['name'].replace("'", "\\'")

    return f"""-- Item: {data['name']} (ID: {data['id']})
DELETE FROM `item_template` WHERE `entry` = {data['id']};
INSERT INTO `item_template` (`entry`, `name`, `ItemLevel`, `Quality`, `class`, `subclass`, `displayid`, `InventoryType`) VALUES
({data['id']}, '{safe_name}', {data['level']}, {data['quality']}, {data['class_id']}, {data['subclass_id']}, {data['display_id']}, {data['inventory_type']});"""

def generate_creature_template_sql(data):
    """Генерирует SQL для creature_template."""
    safe_name = data['name'].replace("'", "\\'")
    safe_subname = data['subname'].replace("'", "\\'")

    sql = f"""-- Creature: {safe_name} (Entry: {data['id']})
-- Detected: Level {data['min_level']}-{data['max_level']}, Rank {data['rank']}, Health {data['health']}, Mana {data['mana']}
DELETE FROM `creature_template` WHERE `entry` = {data['id']};
INSERT INTO `creature_template`
(`entry`, `modelid1`, `name`, `subname`, `minlevel`, `maxlevel`, `rank`, `HealthModifier`, `ManaModifier`, `DamageModifier`, `ExperienceModifier`)
VALUES
({data['id']}, {data['display_id']}, '{safe_name}', '{safe_subname}', {data['min_level']}, {data['max_level']}, {data['rank']}, 1.0, 1.0, 1.0, 1.0);"""
    return sql

def generate_loot_sql(data):
    """Генерирует INSERT запрос для creature_loot_template."""
    npc_id = data['id']
    npc_name = data['name'].replace("'", "\\'")

    sql = f"-- Loot for {npc_name} (Entry: {npc_id})\n"
    # Очищаем старый лут для этого NPC (опционально)
    sql += f"DELETE FROM `creature_loot_template` WHERE `Entry` = {npc_id};\n"
    sql += "INSERT INTO `creature_loot_template` (`Entry`, `Item`, `Reference`, `Chance`, `QuestRequired`, `LootMode`, `GroupId`, `MinCount`, `MaxCount`, `Comment`) VALUES\n"

    rows = []
    for item in data['loot']:
        safe_item_name = item['name'].replace("'", "\\'")
        rows.append(f"({npc_id}, {item['id']}, 0, {item['chance']}, 0, 1, 0, {item['min']}, {item['max']}, '{safe_item_name}')")

    sql += ",\n".join(rows) + ";"
    return sql

def generate_object_loot_sql(data):
    """Генерирует INSERT запрос для gameobject_loot_template."""
    obj_id = data['id']
    obj_name = data['name'].replace("'", "\\'")

    sql = f"-- Loot for {obj_name} (Entry: {obj_id})\n"
    sql += f"DELETE FROM `gameobject_loot_template` WHERE `Entry` = {obj_id};\n"
    sql += "INSERT INTO `gameobject_loot_template` (`Entry`, `Item`, `Reference`, `Chance`, `QuestRequired`, `LootMode`, `GroupId`, `MinCount`, `MaxCount`, `Comment`) VALUES\n"

    rows = []
    for item in data['loot']:
        safe_item_name = item['name'].replace("'", "\\'")
        rows.append(f"({obj_id}, {item['id']}, 0, {item['chance']}, 0, 1, 0, {item['min']}, {item['max']}, '{safe_item_name}')")

    sql += ",\n".join(rows) + ";"
    return sql

def fetch_vendor_data(npc_id, lang='ru', version='', proxies=None):
    """Получает список товаров, продаваемых NPC (парсинг JS)."""
    domain = "ru.wowhead.com" if lang == 'ru' else "www.wowhead.com"
    prefix = f"{version}/" if version else ""
    url = f"https://{domain}/{prefix}npc={npc_id}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers, proxies=proxies, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'lxml')

        # Имя NPC
        h1 = soup.find('h1', class_='heading-size-1')
        npc_name = h1.text.strip() if h1 else f"Vendor {npc_id}"

        # Поиск данных sells
        sells_data_text = ""
        target_id = "id: 'sells'"

        for script in soup.find_all('script'):
            if not script.string: continue

            if "new Listview" in script.string and target_id in script.string:
                listviews = script.string.split('new Listview')

                for lv in listviews:
                    if target_id in lv:
                        data_match = re.search(r"data:\s*\[", lv)
                        if data_match:
                            start_idx = data_match.end() - 1
                            balance = 0
                            for i, char in enumerate(lv[start_idx:], start_idx):
                                if char == '[': balance += 1
                                elif char == ']':
                                    balance -= 1
                                    if balance == 0:
                                        sells_data_text = lv[start_idx:i+1]
                                        break
                        if sells_data_text: break
            if sells_data_text: break

        if not sells_data_text:
            return None, "Этот NPC ничего не продает (или данные не найдены)."

        items = []

        # Ручной разбор
        raw_objects = []
        brace_level = 0
        current_obj_chars = []

        clean_content = sells_data_text.strip()
        if clean_content.startswith('[') and clean_content.endswith(']'):
            clean_content = clean_content[1:-1]

        for char in clean_content:
            if char == '{':
                if brace_level == 0:
                    current_obj_chars = []
                brace_level += 1
                current_obj_chars.append(char)
            elif char == '}':
                brace_level -= 1
                current_obj_chars.append(char)
                if brace_level == 0:
                    raw_objects.append("".join(current_obj_chars))
            elif brace_level > 0:
                current_obj_chars.append(char)

        for raw in raw_objects:
            id_match = re.search(r'["\']?id["\']?\s*:\s*(\d+)', raw)
            if not id_match: continue
            item_id = id_match.group(1)

            # Исправленный regex для имени
            name_match = re.search(r'["\']?name["\']?\s*:\s*["\'](.*?)["\']', raw)
            name = "Unknown"
            if name_match:
                try:
                    name = name_match.group(1).encode('raw_unicode_escape').decode('unicode_escape')
                except Exception:
                    name = name_match.group(1)

            # Уровень предмета
            level_match = re.search(r'["\']?level["\']?\s*:\s*(\d+)', raw)
            level = level_match.group(1) if level_match else "0"

            # Цена покупки (buyprice) в меди
            price_match = re.search(r'["\']?buyprice["\']?\s*:\s*(\d+)', raw)
            price = price_match.group(1) if price_match else "0"

            items.append({'id': item_id, 'name': name, 'level': level, 'price': price})

        return {'id': npc_id, 'name': npc_name, 'sells': items}, None

    except Exception as e:
        return None, f"Ошибка при загрузке вендора: {e}"

def fetch_trainer_data(npc_id, lang='ru', version='', proxies=None):
    """Получает список заклинаний, которым обучает NPC."""
    domain = "ru.wowhead.com" if lang == 'ru' else "www.wowhead.com"
    prefix = f"{version}/" if version else ""
    url = f"https://{domain}/{prefix}npc={npc_id}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers, proxies=proxies, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')

        h1 = soup.find('h1', class_='heading-size-1')
        npc_name = h1.text.strip() if h1 else f"Trainer {npc_id}"

        # Ищем teaches-ability (способности) или teaches-recipe (профессии)
        target_ids = ["id: 'teaches-ability'", "id: 'teaches-recipe'"]
        data_text = ""

        for script in soup.find_all('script'):
            if not script.string: continue
            if "new Listview" in script.string:
                listviews = script.string.split('new Listview')
                for lv in listviews:
                    if any(tid in lv for tid in target_ids):
                        data_match = re.search(r"data:\s*\[", lv)
                        if data_match:
                            start_idx = data_match.end() - 1
                            balance = 0
                            for i, char in enumerate(lv[start_idx:], start_idx):
                                if char == '[': balance += 1
                                elif char == ']':
                                    balance -= 1
                                    if balance == 0:
                                        data_text = lv[start_idx:i+1]
                                        break
                        if data_text: break
            if data_text: break

        spells = []
        if data_text:
            # Упрощенный парсинг объектов
            clean_content = data_text.strip()[1:-1] # убираем [ ]
            # Разбиваем по '},{' - это грубый метод, но для простых списков работает
            # Более надежно было бы использовать brace counting из других функций, но для экономии места:
            raw_objects = re.split(r'\}\s*,\s*\{', clean_content)

            for raw in raw_objects:
                id_m = re.search(r'["\']?id["\']?\s*:\s*(\d+)', raw)
                if not id_m: continue

                name_m = re.search(r'["\']?name["\']?\s*:\s*["\'](.*?)["\']', raw)
                name = "Unknown"
                if name_m:
                    try: name = name_m.group(1).encode('raw_unicode_escape').decode('unicode_escape')
                    except: name = name_m.group(1)

                cost_m = re.search(r'["\']?trainingcost["\']?\s*:\s*(\d+)', raw)
                cost = cost_m.group(1) if cost_m else "0"

                lvl_m = re.search(r'["\']?level["\']?\s*:\s*(\d+)', raw)
                req_lvl = lvl_m.group(1) if lvl_m else "0"

                spells.append({'id': id_m.group(1), 'name': name, 'cost': cost, 'req_level': req_lvl})

        return {'id': npc_id, 'name': npc_name, 'spells': spells}, None

    except Exception as e:
        return None, f"Ошибка при загрузке тренера: {e}"

def generate_vendor_sql(data):
    """Генерирует SQL запрос для npc_vendor."""
    npc_id = data['id']
    npc_name = data['name'].replace("'", "\\'")

    sql = f"-- Vendor items for {npc_name} (Entry: {npc_id})\n"
    sql += f"DELETE FROM `npc_vendor` WHERE `entry` = {npc_id};\n"
    sql += "INSERT INTO `npc_vendor` (`entry`, `slot`, `item`, `maxcount`, `incrtime`, `ExtendedCost`) VALUES\n"

    rows = []
    for i, item in enumerate(data['sells'], 1):
        # slot заполняем по порядку, начиная с 1
        rows.append(f"({npc_id}, {i}, {item['id']}, 0, 0, 0)")

    sql += ",\n".join(rows) + ";"
    return sql

def generate_trainer_sql(data):
    """Генерирует SQL запрос для npc_trainer."""
    npc_id = data['id']
    npc_name = data['name'].replace("'", "\\'")

    sql = f"-- Trainer spells for {npc_name} (Entry: {npc_id})\n"
    sql += f"DELETE FROM `npc_trainer` WHERE `entry` = {npc_id};\n"
    sql += "INSERT INTO `npc_trainer` (`entry`, `spell`, `spellcost`, `reqskill`, `reqskillvalue`, `reqlevel`) VALUES\n"

    rows = [f"({npc_id}, {s['id']}, {s['cost']}, 0, 0, {s['req_level']})" for s in data['spells']]
    sql += ",\n".join(rows) + ";"
    return sql

def generate_achievement_criteria_sql(data):
    """Генерирует шаблон SQL для achievement_criteria_data."""
    ach_id = data['id']
    ach_name = data['name'].replace("'", "\\'")

    sql = f"-- Achievement: {ach_name} (ID: {ach_id})\n"
    sql += "-- Шаблон для achievement_criteria_data (Дополнительные данные условий)\n"
    sql += "-- Common types: 1=Creature, 6=Map, 7=Spell, 11=EquipItem\n"

    for c in data['criteria']:
        safe_name = c['name'].replace("'", "\\'")
        sql += f"\n-- Criteria: {safe_name} (ID: {c['id']})\n"
        sql += f"DELETE FROM `achievement_criteria_data` WHERE `criteria_id` = {c['id']};\n"
        sql += f"INSERT INTO `achievement_criteria_data` (`criteria_id`, `type`, `value1`, `value2`, `ScriptName`) VALUES\n"
        sql += f"({c['id']}, 0, 0, 0, ''); -- Установите type и value1 (например, ID моба)\n"

    return sql

def generate_achievement_reward_sql(data):
    """Генерирует SQL для achievement_reward."""
    ach_id = data['id']

    if not data['rewards']['title'] and not data['rewards']['item']:
        return None

    title_id = data['rewards']['title']['id'] if data['rewards']['title'] else '0'
    item_id = data['rewards']['item']['id'] if data['rewards']['item'] else '0'

    sql = f"-- Reward for Achievement {ach_id}\n"
    sql += f"DELETE FROM `achievement_reward` WHERE `ID` = {ach_id};\n"
    sql += "INSERT INTO `achievement_reward` (`ID`, `TitleA`, `TitleH`, `ItemID`, `Sender`, `Subject`, `Body`, `MailTemplate`) VALUES\n"
    sql += f"({ach_id}, {title_id}, {title_id}, {item_id}, 0, '', '', 0);"
    return sql

def fetch_zone_data(zone_id, lang='ru', version='', proxies=None):
    """Получает список NPC, обитающих в зоне."""
    domain = "ru.wowhead.com" if lang == 'ru' else "www.wowhead.com"
    prefix = f"{version}/" if version else ""
    url = f"https://{domain}/{prefix}zone={zone_id}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers, proxies=proxies, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'lxml')

        h1 = soup.find('h1', class_='heading-size-1')
        zone_name = h1.text.strip() if h1 else f"Zone {zone_id}"

        # Поиск списка NPC (Listview id='npcs')
        npcs_data_text = ""
        target_id = "id: 'npcs'"

        for script in soup.find_all('script'):
            if not script.string: continue

            if "new Listview" in script.string and target_id in script.string:
                listviews = script.string.split('new Listview')
                for lv in listviews:
                    if target_id in lv:
                        data_match = re.search(r"data:\s*\[", lv)
                        if data_match:
                            start_idx = data_match.end() - 1
                            balance = 0
                            for i, char in enumerate(lv[start_idx:], start_idx):
                                if char == '[': balance += 1
                                elif char == ']':
                                    balance -= 1
                                    if balance == 0:
                                        npcs_data_text = lv[start_idx:i+1]
                                        break
                        if npcs_data_text: break
            if npcs_data_text: break

        if not npcs_data_text:
            return None, "Список NPC в этой зоне не найден."

        npcs = []
        # Ручной разбор
        raw_objects = []
        brace_level = 0
        current_obj_chars = []

        clean_content = npcs_data_text.strip()
        if clean_content.startswith('[') and clean_content.endswith(']'):
            clean_content = clean_content[1:-1]

        for char in clean_content:
            if char == '{':
                if brace_level == 0: current_obj_chars = []
                brace_level += 1
                current_obj_chars.append(char)
            elif char == '}':
                brace_level -= 1
                current_obj_chars.append(char)
                if brace_level == 0: raw_objects.append("".join(current_obj_chars))
            elif brace_level > 0:
                current_obj_chars.append(char)

        for raw in raw_objects:
            id_m = re.search(r'["\']?id["\']?\s*:\s*(\d+)', raw)
            if not id_m: continue

            name_m = re.search(r'["\']?name["\']?\s*:\s*["\'](.*?)["\']', raw)
            name = "Unknown"
            if name_m:
                try: name = name_m.group(1).encode('raw_unicode_escape').decode('unicode_escape')
                except: name = name_m.group(1)

            minlvl_m = re.search(r'["\']?minlevel["\']?\s*:\s*(\d+)', raw)
            maxlvl_m = re.search(r'["\']?maxlevel["\']?\s*:\s*(\d+)', raw)

            npcs.append({
                'id': id_m.group(1),
                'name': name,
                'min_lvl': minlvl_m.group(1) if minlvl_m else "?",
                'max_lvl': maxlvl_m.group(1) if maxlvl_m else "?"
            })

        return {'id': zone_id, 'name': zone_name, 'npcs': npcs}, None

    except Exception as e:
        return None, f"Ошибка при загрузке зоны: {e}"

def fetch_achievement_data(ach_id, lang='ru', version='', proxies=None):
    """Получает данные об ачивке (критерии) с Wowhead."""
    domain = "ru.wowhead.com" if lang == 'ru' else "www.wowhead.com"
    prefix = f"{version}/" if version else ""
    url = f"https://{domain}/{prefix}achievement={ach_id}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
    }

    try:
        response = requests.get(url, headers=headers, proxies=proxies, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'lxml')

        h1 = soup.find('h1', class_='heading-size-1')
        ach_name = h1.text.strip() if h1 else f"Achievement {ach_id}"

        # Поиск критериев (Listview id='criteria-of' или 'criteria')
        criteria_data_text = ""
        target_ids = ["id: 'criteria-of'", "id: 'criteria'"]

        for script in soup.find_all('script'):
            if not script.string: continue

            if "new Listview" in script.string:
                # Разбиваем скрипт на отдельные Listview
                listviews = script.string.split('new Listview')
                for lv in listviews:
                    if any(tid in lv for tid in target_ids):
                        data_match = re.search(r"data:\s*\[", lv)
                        if data_match:
                            start_idx = data_match.end() - 1
                            balance = 0
                            for i, char in enumerate(lv[start_idx:], start_idx):
                                if char == '[': balance += 1
                                elif char == ']':
                                    balance -= 1
                                    if balance == 0:
                                        criteria_data_text = lv[start_idx:i+1]
                                        break
                        if criteria_data_text: break
            if criteria_data_text: break

        criteria = []
        if criteria_data_text:
            raw_objects = []
            brace_level = 0
            current_obj_chars = []

            clean_content = criteria_data_text.strip()
            if clean_content.startswith('[') and clean_content.endswith(']'):
                clean_content = clean_content[1:-1]

            for char in clean_content:
                if char == '{':
                    if brace_level == 0: current_obj_chars = []
                    brace_level += 1
                    current_obj_chars.append(char)
                elif char == '}':
                    brace_level -= 1
                    current_obj_chars.append(char)
                    if brace_level == 0: raw_objects.append("".join(current_obj_chars))
                elif brace_level > 0:
                    current_obj_chars.append(char)

            for raw in raw_objects:
                id_m = re.search(r'["\']?id["\']?\s*:\s*(\d+)', raw)
                if not id_m: continue

                name_m = re.search(r'["\']?name["\']?\s*:\s*["\'](.*?)["\']', raw)
                name = name_m.group(1).encode('raw_unicode_escape').decode('unicode_escape') if name_m else "Criteria"
                criteria.append({'id': id_m.group(1), 'name': name})

        # Поиск наград (Звания, Предметы)
        rewards = {'title': None, 'item': None}
        reward_node = soup.find(string=re.compile(r"^(Reward|Награда):"))
        if reward_node:
            parent = reward_node.parent
            # Звание
            title_link = parent.find('a', href=re.compile(r'/title=(\d+)'))
            if title_link:
                tid = re.search(r'/title=(\d+)', title_link['href'])
                if tid: rewards['title'] = {'id': tid.group(1), 'name': title_link.text}

            # Предмет
            item_link = parent.find('a', href=re.compile(r'/item=(\d+)'))
            if item_link:
                iid = re.search(r'/item=(\d+)', item_link['href'])
                if iid: rewards['item'] = {'id': iid.group(1), 'name': item_link.text}

        return {'id': ach_id, 'name': ach_name, 'criteria': criteria, 'rewards': rewards}, None

    except Exception as e:
        return None, f"Ошибка при загрузке ачивки: {e}"

def generate_quest_sql(data):
    """Генерирует чистый, динамический SQL для quest_template (Master/Retail)."""
    safe_title = data['name'].replace("'", "\\'")

    # Основные колонки
    columns = ['ID', 'QuestLevel', 'MinLevel', 'LogTitle']
    values = [data['id'], data['level'] or 0, data['reqLevel'] or 0, f"'{safe_title}'"]

    # Текст (добавляем только если есть)
    if data['objectives']:
        columns.append('LogDescription')
        values.append(f"'{data['objectives'].replace('\'', '\\\'')}'")
    if data['description']:
        columns.append('QuestDescription')
        values.append(f"'{data['description'].replace('\'', '\\\'')}'")
    if data['completion']:
        # В новых ядрах AreaDescription часто используется для текста завершения
        columns.append('AreaDescription')
        values.append(f"'{data['completion'].replace('\'', '\\\'')}'")

    # Деньги
    if int(data['rewards']['money']) > 0:
        columns.append('RewardMoney')
        values.append(data['rewards']['money'])

    # Требования (NPC/GO)
    for i, req in enumerate(data['req_kills'][:4], 1):
        if int(req['id']) != 0:
            columns.append(f'RequiredNpcOrGo{i}')
            values.append(req['id'])
            columns.append(f'RequiredNpcOrGoCount{i}')
            values.append(req['count'])

    # Требования (Items)
    for i, item in enumerate(data['req_items'][:4], 1):
        if int(item['id']) != 0:
            columns.append(f'ItemDrop{i}')
            values.append(item['id'])
            columns.append(f'ItemDropQuantity{i}')
            values.append(item['count'])

    # Награды (Items)
    for i, item in enumerate(data['rewards']['items'][:6], 1):
        if int(item['id']) != 0:
            columns.append(f'RewardItem{i}')
            values.append(item['id'])
            columns.append(f'RewardAmount{i}')
            values.append(item['count'])

    # Награды (Choice Items)
    for i, item in enumerate(data['rewards']['choice_items'][:6], 1):
        if int(item['id']) != 0:
            columns.append(f'RewardChoiceItem{i}')
            values.append(item['id'])
            columns.append(f'RewardChoiceAmount{i}')
            values.append(item['count'])

    # Сборка запроса
    cols_str = ", ".join([f"`{c}`" for c in columns])
    vals_str = ", ".join([str(v) for v in values])

    sql = f"-- Quest: {safe_title} (ID: {data['id']})\n"
    if int(data['rewards']['xp']) > 0:
        sql += f"-- XP: {data['rewards']['xp']} (Set RewardXPDifficulty manually if needed)\n"
    sql += f"DELETE FROM `quest_template` WHERE `ID` = {data['id']};\n"
    sql += f"INSERT INTO `quest_template` ({cols_str}) VALUES\n({vals_str});"

    # Если есть предыдущий квест, добавляем запись в quest_template_addon
    if int(data['prev_quest']) > 0:
        sql += f"\n\n-- Addon data (Chain)\n"
        sql += f"DELETE FROM `quest_template_addon` WHERE `ID` = {data['id']};\n"
        sql += f"INSERT INTO `quest_template_addon` (`ID`, `PrevQuestID`) VALUES ({data['id']}, {data['prev_quest']});"

    return sql

# --- ИНТЕРФЕЙС (UI) ---

st.title("⚔️ Wowhead Item Parser")
st.markdown("Простой инструмент для получения данных о предметах с Wowhead.")

# Боковая панель с настройками
with st.sidebar:
    st.header("Настройки")
    search_mode = st.radio("Что ищем?", ('Предмет (Item)', 'NPC (Loot)', 'Объект (Game Object)', 'Вендор (Vendor)', 'Тренер (Trainer)', 'Квест (Quest)', 'Зона (Zone)', 'Ачивка (Achievement)'), index=0)
    language = st.radio("Язык поиска:", ('ru', 'en'), index=0)

    version_option = st.selectbox("Версия игры:", ('Auto', 'Retail', 'WotLK', 'Cataclysm', 'Classic Era'), index=0)
    version_map = {
        'Retail': '',
        'WotLK': 'wotlk',
        'Cataclysm': 'cata',
        'Classic Era': 'classic'
    }

    # Настройки прокси
    use_proxy = st.checkbox("Использовать прокси")
    proxy_dict = None
    if use_proxy:
        proxy_url = st.text_input("URL прокси:", placeholder="http://user:pass@ip:port")
        if proxy_url:
            proxy_dict = {"http": proxy_url, "https": proxy_url}

    if search_mode.startswith('Предмет'):
        help_text = "ID предмета (например 19019)"
    elif search_mode.startswith('NPC'):
        help_text = "ID NPC (например 18401)"
    elif search_mode.startswith('Объект'):
        help_text = "ID объекта (например 179697)"
    elif search_mode.startswith('Квест'):
        help_text = "ID квеста (например 25)"
    elif search_mode.startswith('Зона'):
        help_text = "ID зоны (например 12 для Элвиннского леса)"
    elif search_mode.startswith('Ачивка'):
        help_text = "ID ачивки (например 6)"
    else:
        help_text = "ID NPC (например 54)"
    st.info(f"Введи {help_text}")

# Основная зона ввода
col1, col2 = st.columns([3, 1])
with col1:
    item_id_input = st.text_input("Введите ID:", placeholder="Цифры ID")
with col2:
    st.write("") # Отступ
    st.write("")
    search_btn = st.button("Найти", type="primary", use_container_width=True)

st.divider()

# Логика отображения
if search_btn and item_id_input:
    clean_id = item_id_input.strip()
    if not clean_id.isdigit():
        st.error("Пожалуйста, введите числовой ID.")
    else:
        data = None
        error = None
        ver_found = None

        def smart_search(fetch_func, obj_id, lang, ver_opt, proxies):
            if ver_opt == 'Auto':
                versions = ['', 'wotlk', 'cata', 'classic']
            else:
                versions = [version_map[ver_opt]]

            last_err = None
            for v in versions:
                d, e = fetch_func(obj_id, lang, version=v, proxies=proxies)
                if d:
                    v_name = next((k for k, val in version_map.items() if val == v), 'Retail')
                    if v == '': v_name = 'Retail'
                    return d, None, v_name
                last_err = e
            return None, last_err, None

        if search_mode.startswith('Предмет'):
            with st.spinner('Загрузка предмета...'):
                data, error, ver_found = smart_search(fetch_wowhead_data, clean_id, language, version_option, proxy_dict)
        elif search_mode.startswith('NPC'):
            with st.spinner('Загрузка данных NPC...'):
                data, error, ver_found = smart_search(fetch_npc_data, clean_id, language, version_option, proxy_dict)
        elif search_mode.startswith('Объект'):
            with st.spinner('Загрузка лута объекта...'):
                data, error, ver_found = smart_search(fetch_object_loot, clean_id, language, version_option, proxy_dict)
        elif search_mode.startswith('Вендор'):
            with st.spinner('Загрузка товаров вендора...'):
                data, error, ver_found = smart_search(fetch_vendor_data, clean_id, language, version_option, proxy_dict)
        elif search_mode.startswith('Тренер'):
            with st.spinner('Загрузка заклинаний тренера...'):
                data, error, ver_found = smart_search(fetch_trainer_data, clean_id, language, version_option, proxy_dict)
        elif search_mode.startswith('Квест'):
            with st.spinner('Загрузка квеста...'):
                data, error, ver_found = smart_search(fetch_quest_data, clean_id, language, version_option, proxy_dict)
        elif search_mode.startswith('Зона'):
            with st.spinner('Загрузка списка NPC в зоне...'):
                data, error, ver_found = smart_search(fetch_zone_data, clean_id, language, version_option, proxy_dict)
        elif search_mode.startswith('Ачивка'):
            with st.spinner('Загрузка ачивки...'):
                data, error, ver_found = smart_search(fetch_achievement_data, clean_id, language, version_option, proxy_dict)

        if error:
            st.error(error)
        elif version_option == 'Auto' and ver_found:
            st.info(f"Данные найдены в базе: **{ver_found}**")

        # --- РЕЖИМ ПРЕДМЕТА ---
        elif data and search_mode.startswith('Предмет'):
            # Отображение результатов в красивой карточке
            st.success("Данные успешно получены!")

            with st.container(border=True):
                # Заголовок с цветом качества
                color = get_quality_color(data['quality'])
                st.markdown(f"<h2 style='color: {color}; margin-top:0;'>{data['name']}</h2>", unsafe_allow_html=True)

                tab_info, tab_sql, tab_json = st.tabs(["📜 Обзор", "💾 SQL Запрос", "⚙️ Сырые данные"])

                with tab_info:
                    c1, c2 = st.columns([1, 3])
                    with c1:
                        icon_url = ICON_URL_BASE.format(data['icon'])
                        st.image(icon_url, width=100)
                    with c2:
                        m1, m2, m3 = st.columns(3)
                        m1.metric("ID", data['id'])
                        m2.metric("Уровень", data['level'])
                        m3.metric("Тип", f"{data['subclass']}")
                        st.markdown(f"**Категория:** {data['class']}")
                        st.markdown(f"🔗 [Открыть на Wowhead]({data['link']})")

                with tab_sql:
                    trinity_sql = generate_trinity_sql(data)
                    st.code(trinity_sql, language="sql")
                    st.download_button("Скачать SQL (.sql)", trinity_sql, file_name=f"item_{data['id']}.sql", mime="text/plain", type="primary")

                with tab_json:
                    st.json(data)

        # --- РЕЖИМ NPC ---
        elif data and search_mode.startswith('NPC'):
            st.success(f"Найдено позиций лута: {len(data['loot'])}")

            with st.container(border=True):
                st.subheader(f"NPC: {data['name']} (ID: {data['id']})")

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Уровень", f"{data['min_level']}" if data['min_level'] == data['max_level'] else f"{data['min_level']} - {data['max_level']}")
                col2.metric("Здоровье", data['health'])
                col3.metric("Мана", data['mana'])
                rank_map = {'0': 'Обычный', '1': 'Элита', '2': 'Редкая Элита', '3': 'Босс', '4': 'Редкий'}
                col4.metric("Ранг", rank_map.get(data['rank'], data['rank']))
                if data['subname']:
                     st.caption(f"<{data['subname']}>")

                tab_loot, tab_sql, tab_json = st.tabs(["📦 Лут", "💾 SQL Запрос", "⚙️ Сырые данные"])

                with tab_loot:
                    if data['loot']:
                        table_data = [
                            {"ID": i['id'], "Название": i['name'], "Шанс %": i['chance'], "Мин": i['min'], "Макс": i['max']}
                            for i in data['loot']
                        ]
                        st.dataframe(table_data, use_container_width=True, hide_index=True)
                    else:
                        st.warning("У этого NPC нет таблицы лута (Drop).")

                with tab_sql:
                    # Creature Template SQL
                    st.write("**creature_template** (Базовые статы)")
                    creature_sql = generate_creature_template_sql(data)
                    st.code(creature_sql, language="sql")
                    st.download_button("Скачать Template SQL", creature_sql, file_name=f"creature_{data['id']}.sql", mime="text/plain")
                    st.divider()

                    if data['loot']:
                        st.write("**creature_loot_template** (Лут)")
                        loot_sql = generate_loot_sql(data)
                        st.code(loot_sql, language="sql")
                        st.download_button("Скачать SQL", loot_sql, file_name=f"loot_{data['id']}.sql", mime="text/plain", type="primary")
                    else:
                        st.info("Нет данных для генерации SQL.")

                with tab_json:
                    st.json(data)

        # --- РЕЖИМ ОБЪЕКТА ---
        elif data and search_mode.startswith('Объект'):
            st.success(f"Найдено позиций лута: {len(data['loot'])}")

            with st.container(border=True):
                st.subheader(f"Object: {data['name']} (ID: {data['id']})")

                tab_loot, tab_sql, tab_json = st.tabs(["📦 Лут", "💾 SQL Запрос", "⚙️ Сырые данные"])

                with tab_loot:
                    if data['loot']:
                        table_data = [
                            {"ID": i['id'], "Название": i['name'], "Шанс %": i['chance'], "Мин": i['min'], "Макс": i['max']}
                            for i in data['loot']
                        ]
                        st.dataframe(table_data, use_container_width=True, hide_index=True)
                    else:
                        st.warning("У этого объекта нет таблицы лута (Drop).")

                with tab_sql:
                    if data['loot']:
                        loot_sql = generate_object_loot_sql(data)
                        st.code(loot_sql, language="sql")
                        st.download_button("Скачать SQL", loot_sql, file_name=f"gob_loot_{data['id']}.sql", mime="text/plain", type="primary")

                with tab_json:
                    st.json(data)

        # --- РЕЖИМ ВЕНДОРА ---
        elif data and search_mode.startswith('Вендор'):
            st.success(f"Найдено товаров: {len(data['sells'])}")

            with st.container(border=True):
                st.subheader(f"Vendor: {data['name']} (ID: {data['id']})")

                tab_sells, tab_sql, tab_json = st.tabs(["💰 Товары", "💾 SQL Запрос", "⚙️ Сырые данные"])

                with tab_sells:
                    if data['sells']:
                        table_data = [
                            {"ID": i['id'], "Название": i['name'], "Уровень": i['level'], "Цена": format_money(i['price'])}
                            for i in data['sells']
                        ]
                        st.dataframe(table_data, use_container_width=True, hide_index=True)
                    else:
                        st.warning("У этого NPC нет списка продаваемых товаров.")

                with tab_sql:
                    if data['sells']:
                        vendor_sql = generate_vendor_sql(data)
                        st.code(vendor_sql, language="sql")
                        st.download_button("Скачать SQL", vendor_sql, file_name=f"vendor_{data['id']}.sql", mime="text/plain", type="primary")

                with tab_json:
                    st.json(data)

        # --- РЕЖИМ ТРЕНЕРА ---
        elif data and search_mode.startswith('Тренер'):
            st.success(f"Найдено заклинаний: {len(data['spells'])}")

            with st.container(border=True):
                st.subheader(f"Trainer: {data['name']} (ID: {data['id']})")

                tab_spells, tab_sql, tab_json = st.tabs(["✨ Заклинания", "💾 SQL Запрос", "⚙️ Сырые данные"])

                with tab_spells:
                    if data['spells']:
                        table_data = [{"ID": i['id'], "Название": i['name'], "Цена": format_money(i['cost']), "Треб. уровень": i['req_level']} for i in data['spells']]
                        st.dataframe(table_data, use_container_width=True, hide_index=True)
                    else:
                        st.warning("Этот NPC ничему не обучает.")

                with tab_sql:
                    if data['spells']:
                        trainer_sql = generate_trainer_sql(data)
                        st.code(trainer_sql, language="sql")
                        st.download_button("Скачать SQL", trainer_sql, file_name=f"trainer_{data['id']}.sql", mime="text/plain", type="primary")

                with tab_json:
                    st.json(data)

        # --- РЕЖИМ КВЕСТА ---
        elif data and search_mode.startswith('Квест'):
            st.success("Квест успешно найден!")
            with st.container(border=True):
                st.subheader(f"Quest: {data['name']} (ID: {data['id']})")

                tab_info, tab_sql, tab_json = st.tabs(["📜 Инфо", "💾 SQL Запрос", "⚙️ Сырые данные"])

                with tab_info:
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Уровень", f"{data['level']}")
                    m2.metric("Требует", f"{data['reqLevel']}")
                    m3.metric("Опыт", f"{data['rewards']['xp']}")
                    if data['prev_quest'] != "0": m4.metric("Пред. квест", data['prev_quest'])
                    if data['next_quest'] != "0": m4.metric("След. квест", data['next_quest'])

                    money_str = format_money(data['rewards']['money'])
                    st.markdown(f"**Деньги:** {money_str}")

                    if data['rewards']['items']:
                        st.write("**Предметы:**")
                        for item in data['rewards']['items']:
                            st.text(f"- ID {item['id']} (Кол-во: {item['count']})")

                    if data['rewards']['choice_items']:
                        st.write("**Предметы на выбор:**")
                        for item in data['rewards']['choice_items']:
                            st.text(f"- ID {item['id']} (Кол-во: {item['count']})")

                    st.divider()
                    st.caption("Цели и Описание")
                    st.text_area("Цели", data['objectives'], disabled=True, height=100)
                    st.text_area("Описание", data['description'], disabled=True, height=150)
                    if data['completion']:
                        st.text_area("Завершение", data['completion'], disabled=True, height=100)

                with tab_sql:
                    quest_sql = generate_quest_sql(data)
                    st.code(quest_sql, language="sql")
                    st.download_button("Скачать SQL", quest_sql, file_name=f"quest_{data['id']}.sql", mime="text/plain", type="primary")

                with tab_json:
                    st.json(data)

        # --- РЕЖИМ ЗОНЫ ---
        elif data and search_mode.startswith('Зона'):
            st.success(f"Найдено NPC: {len(data['npcs'])}")

            with st.container(border=True):
                st.subheader(f"Zone: {data['name']} (ID: {data['id']})")

                tab_list, tab_json = st.tabs(["📋 Список NPC", "⚙️ Сырые данные"])

                with tab_list:
                    if data['npcs']:
                        table_data = [
                            {"ID": i['id'], "Имя": i['name'], "Мин. ур": i['min_lvl'], "Макс. ур": i['max_lvl']}
                            for i in data['npcs']
                        ]
                        st.dataframe(table_data, use_container_width=True, hide_index=True)

                        txt_list = "\n".join([f"{i['id']} - {i['name']}" for i in data['npcs']])
                        st.download_button("Скачать список (TXT)", txt_list, file_name=f"zone_{data['id']}_npcs.txt", type="primary")
                    else:
                        st.warning("NPC не найдены.")

                with tab_json:
                    st.json(data)

        # --- РЕЖИМ АЧИВКИ ---
        elif data and search_mode.startswith('Ачивка'):
            st.success(f"Найдено критериев: {len(data['criteria'])}")

            with st.container(border=True):
                st.subheader(f"Achievement: {data['name']} (ID: {data['id']})")

                # Отображение наград
                if data['rewards']['title'] or data['rewards']['item']:
                    if data['rewards']['title']:
                        st.success(f"🏆 Награда (Звание): **{data['rewards']['title']['name']}** (ID: {data['rewards']['title']['id']})")
                    if data['rewards']['item']:
                        st.success(f"🎁 Награда (Предмет): **{data['rewards']['item']['name']}** (ID: {data['rewards']['item']['id']})")
                    st.divider()

                tab_crit, tab_sql, tab_json = st.tabs(["📋 Критерии", "💾 SQL Запрос", "⚙️ Сырые данные"])

                with tab_crit:
                    if data['criteria']:
                        table_data = [{"ID": i['id'], "Название": i['name']} for i in data['criteria']]
                        st.dataframe(table_data, use_container_width=True, hide_index=True)
                    else:
                        st.warning("Критерии не найдены или ачивка не имеет списка.")

                with tab_sql:
                    full_sql = ""
                    if data['criteria']:
                        full_sql += generate_achievement_criteria_sql(data) + "\n\n"

                    reward_sql = generate_achievement_reward_sql(data)
                    if reward_sql:
                        full_sql += reward_sql

                    if full_sql:
                        st.code(full_sql, language="sql")
                        st.download_button("Скачать SQL", full_sql, file_name=f"achievement_{data['id']}.sql", mime="text/plain", type="primary")
                    else:
                        st.info("Нет данных для генерации SQL.")

                with tab_json:
                    st.json(data)

elif search_btn:
    st.warning("Введите ID для поиска.")
