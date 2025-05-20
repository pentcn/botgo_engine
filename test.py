from pocketbase import PocketBase

client = PocketBase("http://192.168.0.33:8090")


admin_data = client.admins.auth_with_password("7534199@qq.com", "@Dian2008z")
print(admin_data.is_valid)
print(client.collection("deals").get_list(1, 30))
