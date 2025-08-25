import bcrypt

password = "SR123456"
password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

print("新生成的哈希值：")
print(password_hash)