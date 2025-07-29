import pandas as pd
from ydata_profiling import ProfileReport

df = pd.read_csv("/Users/tweber/Downloads/iris.csv")
print(df)
profile = ProfileReport(df, title="Profiling Report")
# As a JSON string
json_data = profile.to_json()
# from pprint import pprint

# pprint(json_data)

profile.to_file("your_report.json")
profile.to_file("your_report.html")
