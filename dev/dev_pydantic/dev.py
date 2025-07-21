from bson import ObjectId
from depictio_models.models.deltatables import DeltaTableAggregated, Test

a = Test(test="test")
b = DeltaTableAggregated(data_collection_id=ObjectId(), delta_table_location="test")
print(a)
print(b)
