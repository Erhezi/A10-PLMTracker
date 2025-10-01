# the code checks when adding (Item Group, Item, Replacement Item) from ItemLink,
# when we split the record to (Item Group, Item, Side O), (Item Group, Replacement Item, Side R),
# and put into ItemGroup, will this violiates the unique constraint on (Item Group, Item, Side)?

# given that our (Item, Replacement Item) relation can only be 1-1, 1-many, or many-1,
# wihtout chainning, selfing or cycles, we know that for each Item, and all the 1-many or 
# many-1 relations need to be unified under the same Item Group.
# So we know that when we add a new (Item Group, Item, Replacement Item) record,
# if Item already exists in ItemGroup with the same Side, we should assign the same Item Group for the ItemLink addition
# if Item and replacement Item during addition both exist in ItemGroup with different Item Groups assigned, we know we have many-to-many and it is not allowed.
# if Item already exists in ItemGroup with the opposite Side, we know we have chainning or selfing or cyclic relations, which is not allowed.