from depictio_models.models.deltatables import Test, DeltaTableAggregated
from bson import ObjectId
a = Test(test="test")
b = DeltaTableAggregated(data_collection_id=ObjectId(), delta_table_location="test")
print(a)
print(b)