import time
import requests
import constant
bot_token = constant.TOKEN

discount_with_one_stock = 10 #Процент скидки, которая выставляется при обнаружении единичного остатка
class Notification:
    def __init__(self, user, notification_status, message_text, url, buttons):
        self.user = user
        self.notification_status = notification_status
        self.message_text = message_text
        self.url = url
        self.buttons = buttons

    def send_notification(self):
        if self.notification_status:
            if self.buttons:
                json_data = {
                    'chat_id': self.user,
                    'text': self.message_text,
                    'reply_markup': {'inline_keyboard': [self.buttons]}
                }
            else:
                json_data = {
                    'chat_id': self.user,
                    'text': self.message_text,
                }
            response = requests.get(url=self.url, json=json_data)
            self.buttons = None


def get_users_item_price(item, token, discount_flag=False):
    price_token = token
    header = {'Authorization': price_token}
    url = 'https://discounts-prices-api.wb.ru/api/v2/list/goods/filter'
    if discount_flag:
        params = {'limit': 1000}
    else:
        params = {'limit': 1000,
                'filterNmID': item}
    response = requests.get(url=url, headers=header, params=params)
    if response.status_code == 200:
        resp_json = response.json()
        if len(resp_json['data']['listGoods']) != 0:
            if discount_flag:
                return resp_json['data']['listGoods']
            else:
                user_price = resp_json['data']['listGoods'][0]['sizes'][0]['discountedPrice']
            return user_price
        else:
            return False
    else:
        return False

def get_wb_item_price(item, wb_discount, status=2):
    url = f'https://card.wb.ru/cards/detail?appType=0&curr=rub&dest=-444908&spp=30&nm={item}'
    site = requests.get(url)
    try:
        sale_price = int(site.json()['data']['products'][0]['salePriceU']) / 100
    except:
        return False
    price_with_wb_discount = sale_price * (1-wb_discount/100)
    if status == 1:
        return sale_price
    else:
        return int(price_with_wb_discount)

def calculate_price(user_price, wb_sale_price, need_price, dif_price=0, real_price_flag=False):
    discount = wb_sale_price / user_price
    need_user_price = int((need_price - dif_price) / discount + 0.5)
    fake_user_price = need_user_price * 2
    if real_price_flag:
        return need_user_price
    else:
        return fake_user_price

def change_wb_price(price_list, token):
    '''price_list: [{"nmID": int(article_wb), "price": round(price_with_fake_discount), "discount": 50}]'''

    header = {'Authorization': token}
    url = 'https://discounts-prices-api.wb.ru/api/v2/upload/task'
    response = requests.post(url=url, headers=header, json={'data': price_list})
    return response

def get_user_id_token_dict(url):
    url = url + '/users_get_all'
    response = requests.get(url)
    if response.status_code == 200:
        user_id_token_dict = response.json()
        new_users_dict = {}
        for i in user_id_token_dict['users_list']:
            podpiska_status = i['podpiska_status']
            if i['user_status'] != 0 and podpiska_status > 0:
                new_users_dict[i['user_id']] = {'token': i['token'], 'notification_status': i['notification_status'],
                                                'user_status': i['user_status'], 'warehouse': i['warehouse']}
        return new_users_dict
    else:
        return response

def get_items_of_users(url, user_id):
    '''Возвращает список товаров принадлежащих пользователю без неактивных товаров, а так же без исключений
     и товараов удалённых из рекламных кампаний'''
    url = url + '/items_get_all'
    params = {'user_id': user_id}
    response = requests.get(url, params=params)
    if response.status_code == 200:
        it = response.json()['items_list']
        item_list = [i for i in it if i['status'] not in [0, 5, 10]]
        return item_list
    else:
        return response

def check_ost_and_change_price(token, warehouseId, user_id):
    global Noti
    '''пробуем получить остатки'''
    headers = {'Authorization': token}
    url = 'https://suppliers-api.wildberries.ru/content/v2/get/cards/list'
    cursor = {'limit': 100}
    total = 1
    skus_dict = {}
    skus_list = []
    try:
        while total != 0:
            json = {'settings': {
                'cursor': cursor,
                'filter': {'withPhoto': -1}}
            }
            response = requests.post(url=url, json=json, headers=headers)
            if response.status_code == 200:
                for i in response.json()['cards']:
                    skus_dict[i['sizes'][0]['skus'][0]] = i['nmID']
                    skus_list.append(i['sizes'][0]['skus'][0])
                cursor = response.json()['cursor']
                cursor['limit'] = 100
                total = response.json()['cursor']['total']
            else:
                return 404, []
        if len(skus_list) == 0:
            return 403, []
    except:
        return 404, []

    json = {'skus': skus_list}
    url = f'https://suppliers-api.wildberries.ru/api/v3/stocks/{warehouseId}'
    response = requests.post(url=url, json=json, headers=headers)
    if response.status_code == 200:
        ostatki = response.json()['stocks']
    else:
        return 403, []
    one_stock_list = []
    many_stock_list = []
    for i in ostatki:
        if i['amount'] == 1:
            one_stock_list.append(skus_dict[i['sku']])
        else:
            many_stock_list.append(skus_dict[i['sku']])

    discount_50 = []
    discount_not_50 = []
    all_items = get_users_item_price(item=None, token=token, discount_flag=True)
    '''Получаем информацию о рекламных компаниях'''
    adverts_flag = True
    worked_list, paused_list = get_adverts_list(headers)
    if not worked_list and not paused_list:
        adverts_flag = False
        json_data = {
            'chat_id': user_id,
            'text': f'Токен для рекламы не верный',
        }
        response = requests.get(
            url=f'https://api.telegram.org/bot{bot_token}/sendMessage', json=json_data)
    else:
        paused = get_info_adverts(paused_list, headers)
        worked = get_info_adverts(worked_list, headers)


    '''проверяем товары на единичные остатки'''
    result = requests.get(f'http://127.0.0.1:555/items_get_all', params={'user_id': user_id})
    if result.status_code == 200:
        items_status_10 = [i['item'] for i in result.json()['items_list'] if i['status'] == 10]
        items_status_5 = [i['item'] for i in result.json()['items_list'] if i['status'] == 5]
    else:
        items_status_10 = []
        items_status_5 = []
    uses_items = []
    for i in all_items:
        if i['nmID'] in items_status_5:
            continue

        if i['discount'] != 50 and i['nmID'] in one_stock_list:
            if adverts_flag and len(worked) != 0:
                result = paused_or_delete_items(worked, int(i['nmID']), headers, user_id)

        if i['discount'] == 50 and i['nmID'] in one_stock_list:
            if adverts_flag and len(worked) != 0:
                result = paused_or_delete_items(worked, int(i['nmID']), headers, user_id)
                Noti.buttons = [{'text': 'Перейти в артикул.',
                                 'url': f'https://www.wildberries.ru/catalog/{i["nmID"]}/detail.aspx?targetUrl=GP'}]
                Noti.message_text = f'{i["nmID"]} осталась последняя единица'
                Noti.send_notification()

                discount_50.append({"nmID": int(i['nmID']), "discount": discount_with_one_stock, "price": int(i['sizes'][0]['price'])})
                uses_items.append(int(i['nmID']))

        elif i['discount'] == 50 and i['nmID'] in many_stock_list:
            if adverts_flag and len(paused+worked) != 0:
                result = start_campaign_or_add_items(paused, worked, int(i['nmID']), headers, items_status_10)

        elif i['discount'] != 50 and i['nmID'] in many_stock_list:
            if adverts_flag and len(paused+worked) != 0:
                result = start_campaign_or_add_items(paused, worked, int(i['nmID']), headers, items_status_10)
                discount_not_50.append({"nmID": int(i['nmID']), "discount": 50, "price": int(i['sizes'][0]['price'])})
                uses_items.append(int(i['nmID']))
                Noti.buttons = [{'text': 'Перейти в артикул.',
                                 'url': f'https://www.wildberries.ru/catalog/{i["nmID"]}/detail.aspx?targetUrl=GP'}]
                Noti.message_text = f'{i["nmID"]} цена восстановлена'
                Noti.send_notification()

    change_wb_price(discount_not_50, token)
    change_wb_price(discount_50, token)

    one_stock_list = [i for i in one_stock_list if i not in items_status_5]

    return 200, uses_items + one_stock_list

def check_and_change_price_of_user(token, item_list, wb_discount, user_status, user, warehouseId=None):
    change_items_list = []
    for_bot_sending_list = []
    result = [400, []]

    if user_status == 2:
        if warehouseId == None:
            json_data = {
                'chat_id': user,
                'text': 'Не указан номер склада (Warehouse)'
            }
            response = requests.get(
                url=f'https://api.telegram.org/bot{bot_token}/sendMessage', json=json_data)

        else:
            result = check_ost_and_change_price(token, warehouseId, user)

            if result[0] == 404:
                json_data = {
                    'chat_id': user,
                    'text': 'не удалось получить список товаров. Проверьте токен'
                }
                response = requests.get(
                    url=f'https://api.telegram.org/bot{bot_token}/sendMessage', json=json_data)


            elif result[0] == 403:
                json_data = {
                    'chat_id': user,
                    'text': 'ВБ вернул пустой список товаров'
                }
                response = requests.get(
                    url=f'https://api.telegram.org/bot{bot_token}/sendMessage', json=json_data)

    for i in item_list:
        item = i['item']
        if item in result[1]:
            continue
        minimal_price = i['price']
        item_status = i['status']
        konkurent_item = i['konkurent_item']
        dif_price = i['dif_price']
        recomended_price = i['recomended_price']

        incide_price = int(get_users_item_price(item, token))
        if incide_price == False:
            return f'Не удалось получить внутреннюю цену товара "{item}"\n' \
                   f'Проверьте правильность артикула, а так же убедитесь, что Вы используете действующий токен', 405

        out_side_price = get_wb_item_price(item, wb_discount, item_status)

        if not out_side_price:
            return f'не найден артикул "{item}", проверьте правильность написания', 400

        if item_status == 3:
            discount = out_side_price / incide_price
            konkurent_price = get_wb_item_price(konkurent_item, wb_discount, status=2)

            need_price = int(recomended_price * discount + 0.5)

            if konkurent_price:
                if int(konkurent_price - dif_price + 0.5) > int(minimal_price * discount ):
                    need_price = konkurent_price

                    if int(konkurent_price - dif_price + 0.5) > int(recomended_price * discount):
                        need_price = int(recomended_price * discount + 0.5) + dif_price

                elif int(konkurent_price - dif_price + 0.5) < int(minimal_price * discount):
                    need_price = int(minimal_price * discount + 0.5) + dif_price

                if out_side_price - int(need_price + 0.5 - dif_price) == 0:
                    continue

        else:
            need_price = minimal_price
            dif_price = 0
            if int(out_side_price + 0.5) - int(minimal_price + 0.5) == 0:
                continue

        calc_price = calculate_price(incide_price, out_side_price, need_price, dif_price, real_price_flag=False)

        change_items_list.append({'nmID': int(item), 'price': calc_price, 'discount': 50})
        for_bot_sending_list.append([item, out_side_price, need_price - dif_price, konkurent_item])

    if len(change_items_list) > 0:
        change_wb_price(change_items_list, token)
        return for_bot_sending_list, 200
    else:
        return 'Нет товаров для изменения цены', 201

def get_adverts_list(headers):
    url = 'https://advert-api.wb.ru/adv/v1/promotion/count'
    response = requests.get(url=url, headers=headers)
    if response.status_code != 200:
        return None, None
    for i in response.json()['adverts']:
        print(i)
    worked_list = []
    paused_list = []
    for i in response.json()['adverts']:
        advert_list = [j['advertId'] for j in i['advert_list']]
        if i['status'] == 9:
            worked_list = advert_list
        if i['status'] == 11:
            paused_list = advert_list
    return worked_list, paused_list

def get_info_adverts(adverts_list, headers):
    ''':return    [id_adverts, name, len(items), [items]]'''
    url = 'https://advert-api.wb.ru/adv/v1/promotion/adverts'
    response = requests.post(url=url, headers=headers, json=adverts_list)
    if response.status_code == 200:
        advert_name_items_list = []
        for i in response.json():
            advert_name = i['name']
            advert_id = i['advertId']
            items = []
            if i['type'] == 9:
                if 'unitedParams' in i.keys():
                    for j in i['unitedParams']:
                        items.append(*j['nms'])
                else:
                    items = None
            elif i['type'] == 8:
                if 'autoParams' in i.keys():
                    items = i['autoParams']['nms']
                else:
                    items = None
            if items:
                advert_len = len(items)
            else:
                advert_len = None
            advert_name_items_list.append([advert_id, advert_name, advert_len, items, i['type']])
        return advert_name_items_list
    else:
        return []

def paused_or_delete_items(advert_name_items_list, item, headers, user_id):
    global Noti
    for i in advert_name_items_list:
        if not i[3]:
            continue
        else:
            if item in i[3]:
                if i[2] > 1 and i[4] == 8:
                    '''удаляем из списка'''
                    time.sleep(1)
                    url = 'https://advert-api.wb.ru/adv/v1/auto/updatenm'
                    params = {'id': i[0]}
                    json = {'delete': [item]}
                    response = requests.post(url=url, headers=headers, params=params, json=json)
                    if response.status_code == 200:
                        Noti.message_text = f'{item} удалён из кампании {i[1]}'
                        Noti.send_notification()

                        params = {
                            'user_id': user_id,
                            'item': item,
                            'price': 0,
                            'status': 10,
                            'konkurent_item': i[0],
                            'dif_price': 0,
                            'recomended_price': 0
                        }
                        response = requests.post(f'http://127.0.0.1:555/items', params=params)
                        return True

                else:
                    '''Останавливаем кампанию'''
                    time.sleep(1)
                    url = 'https://advert-api.wb.ru/adv/v0/pause'
                    params = {'id': i[0]}
                    response = requests.get(url=url, headers=headers, params=params)
                    if response.status_code == 200:
                        Noti.message_text = f'Кампания {i[1]} приостановлена'
                        Noti.send_notification()
                        return True

def start_campaign_or_add_items(paused, worked, item, headers, items_status_10):
    advert_id = None
    global Noti
    if item in items_status_10:
        result = requests.get(f'http://127.0.0.1:555/items', params={'item': item, 'status': 10})
        if result.status_code == 200:
            advert_id = result.json()['konkurent_item']

    if advert_id:
        advert_name = advert_id
        for i in paused+worked:
            if advert_id == i[0]:
                advert_name = i[1]
                break
        url = 'https://advert-api.wb.ru/adv/v1/auto/updatenm'
        params = {'id': advert_id}
        json = {'add': [item]}
        response = requests.post(url=url, headers=headers, params=params, json=json)
        if response.status_code == 200:
            requests.delete(f'http://127.0.0.1:555/items', params={'item': item, 'status': 10})
            Noti.message_text = f'Товар {item} добавлен в кампанию {advert_name}'
            Noti.send_notification()
        return True

    for i in paused:
        if not i[3]:
            continue
        else:
            if item in i[3]:
                '''Запускаем кампанию'''
                time.sleep(1)
                url = 'https://advert-api.wb.ru/adv/v0/start'
                params = {'id': i[0]}
                response = requests.get(url=url, headers=headers, params=params)
                if response.status_code == 200:
                    Noti.message_text = f'Кампания {i[1]} запущенна'
                    Noti.send_notification()
                    return True



if __name__ == '__main__':
    url = 'http://127.0.0.1:555'
    time_sleep = 600 #секунд


    user_items_dict = {}
    while True:
        wb_discount = int(open('wb_discount.txt').read())
        users_list = get_user_id_token_dict(url)
        for user, value in users_list.items():

            Noti = Notification(user=user, notification_status=value['notification_status'], message_text='',
                                url=f'https://api.telegram.org/bot{bot_token}/sendMessage', buttons=None)

            headers = {'Authorization': value['token']}
            items_list = get_items_of_users(url, user)

            if user in user_items_dict.keys():
                for i in items_list:
                    user_items_dict[user].add(str(i['item']))
            else:
                user_items_dict[user] = {str(items_list[0]['item'])}
                for i in items_list[1:]:
                    user_items_dict[user].add(str(i['item']))

            if time.localtime(time.time()).tm_hour == 21:
                check_user = requests.get(url + '/users', params={'user_id': user})
                if check_user.status_code == 200:
                    podpiska = check_user.json()['users'][0]['podpiska_status']
                    if int(podpiska) <= 0:
                        json_data = {
                            'chat_id': user,
                            'text': 'На Вашем балансе недостаточно баллов для списания. Пополните, что бы бот снова заработал',
                        }
                        response = requests.get(
                            url=f'https://api.telegram.org/bot{bot_token}/sendMessage', json=json_data)
                    else:
                        response = requests.patch(url + '/users', params={'user_id': user, 'podpiska_status': podpiska - len(user_items_dict[user])})
                    del user_items_dict[user]
            result = check_and_change_price_of_user(value['token'], items_list, wb_discount,
                                                    user_status=value['user_status'], warehouseId=value['warehouse'],
                                                    user=user)

            if result[1] == 200:
                Noti.message_text = 'Изменились цены:'
                Noti.send_notification()

                for i in result[0]:
                    if i[3]:
                        Noti.buttons = [{'text': 'Мой арт.',
                                     'url': f'https://www.wildberries.ru/catalog/{i[0]}/detail.aspx?targetUrl=GP'},
                                    {'text': 'Конкурент арт.',
                                     'url': f'https://www.wildberries.ru/catalog/{i[3]}/detail.aspx?targetUrl=GP'}]

                    else:
                        Noti.buttons = [{'text': 'Мой арт.',
                                     'url': f'https://www.wildberries.ru/catalog/{i[0]}/detail.aspx?targetUrl=GP'}]

                    Noti.message_text = f'арт.{i[0]} | старая цена: {i[1]}, новая цена: {i[2]}'
                    Noti.send_notification()

            elif result[1] == 405:
                Noti.message_text = f'{result[0]}'
                Noti.send_notification()

        time.sleep(time_sleep)
















