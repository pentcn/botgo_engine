class Strategy:
    def __init__(self, data):
        self.id = data.get("id")
        self.user = data.get("user")
        self.name = data.get("name")
        self.active = data.get("active")
        self.params = data.get("params")
        self.created = data.get("created")
        self.updated = data.get("updated")
