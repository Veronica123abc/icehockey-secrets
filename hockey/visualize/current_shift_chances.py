import matplotlib.pyplot as plt


def current_shift_chances(data, team_id):
    return (
        data[data.team_id == team_id]
        .groupby(["player_id", "toi_status"])["toi_status"]
        .count()
        .reset_index()
    )