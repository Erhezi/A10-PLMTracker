-- The item and quantity views behind the Fill/Kill main table, reading kill lines from
-- FillKill.vw_MedlineFillKill (10_kill_lines.sql), and the list of Medline's subs the item view reads.
-- Run on O2, database PLM, after 10_kill_lines.sql (the item view reads its InforUOM). Safe to re-run.
--
-- Written on O2 by the module owner; copied here (last on 2026-11-18, from O2's definitions) so they
-- are versioned with the app. If you change a view on O2, change it here too. Two changes first made
-- here are in O2's too: they read FillKill.vw_MedlineFillKill instead of
-- SCSFileIngestor.MedlineFillKill.MedlineFillKill; and (2026-10-14) the UOM conversion (the QOE
-- column) is read for the Infor item, Medline's vendor item in Infor, rather than for Medline's
-- customer item, which isn't always an Infor item (e.g. 1296-DYNJAA04).
--
-- The Infor item is matched on Medline vendor items only (CTE f). Not by manufacturer part alone:
-- different manufacturers share simple part numbers (e.g. 0104), which gives false matches.
--
-- 2026-11-18 (the user, on O2):
--   - vw_MedlineSubList (new): Medline's subs from four sources, each with its rank (SubRank, lower is
--     preferred): 0 Medline's AutoSub list, 1 the Fill/Kill file's Customer Preferred Substitute
--     Item, 2 its Possible Subst. Item, 3 the PBO sub collection (until then the only source).
--   - The item view matches the UOM conversion and the subs on InforUOM (10), Medline's UM as Infor
--     calls it, so a CS line finds the Infor item's CA. Its Medline.Sub comes from vw_MedlineSubList,
--     one row per sub, whatever its source (SUB_VARS counts them). It drops Medline.ParentItem (the
--     app never read it) and adds InforUOM, InforManufacturerNumberByCustomerItem,
--     InforItemActiveByCustomerItem and InforVendorItemActiveByMedlineItem.
--   - The app's account needs SELECT on SCSFileIngestor.MedlineAutoSub.MedlineAutosubRelation
--     (vw_MedlineSubList reads it, and the app reads the item view): a view here doesn't carry
--     permissions into another database.
--
-- 2026-11-19 (first made here): the item view also gives each sub's best rank and its source
-- (Medline.SubRank, Medline.SubDataSource; CTE d already had them). 14's usp_SyncPboSubs reads the
-- rank: it labels each sub with its source, and adds the AutoSub (0) and Customer Preferred (1)
-- ones as approved, the others pending review. If the ranks change, change 14 with them.
--
--   vw_MedlineSubList                 Medline item x UM (as Infor calls it) x sub, with its source and
--                                     rank, and the Medline vendor item's Infor item
--   vw_MedlineFillKillItemCollection  one row per Medline item (and UM; one per sub when it has
--                                     several): description, Infor UOM conversions, Medline sub
--                                     (with its best rank and source), Infor item cross-check, and
--                                     the Infor item's active status, descriptions and commodity code
--   vw_MedlineFillKillQtyAgg          per order date x Sold-To x Medline item: ordered, filled,
--                                     killed quantities and PO line count

SET NOCOUNT ON;
GO

CREATE OR ALTER VIEW FillKill.vw_MedlineSubList as
With vi as(
select distinct item, VendorItem, VendorBuyUOM, [VendorBuyUOM.UOMConversion]
from PLMPreprocessorShared.infor.MDM_VENDORITEM
where active = 'Yes' and vendorBuyUOM <> ''
and VendorName like '%Medline%'
),
sublist as(
select distinct [Medline Item], [SUOM], [Substitute Material Number], 'Medline PBO' as DataSource
from SCSFileIngestor.MedlinePBO.MedlineSubCollection
where [Substitute Material Number] <> ''

union all

select distinct [PRIMARY ML #], coalesce(VendorBuyUOM, '') as VendorBuyUOM,
AutoSub, 'Medline AutoSub' as DataSource
from SCSFileIngestor.MedlineAutoSub.MedlineAutosubRelation [autosub]
left join vi
on autosub.[PRIMARY ML #] = vi.VendorItem

union all

select distinct Item, UM, [Possible Subst. Item], 'Medline FillKill Possible Sub' as DataSource
from SCSFileIngestor.MedlineFillKill.MedlineFillKill
where [Possible Subst. Item] is not null

union all

select distinct Item, UM, [Customer Preferred Substitute Item], 'Medline FillKill Customer Preferred' as DataSource
from SCSFileIngestor.MedlineFillKill.MedlineFillKill
where [Customer Preferred Substitute Item] is not null
)

select sublist.[Medline Item], coalesce(uom.LawsonValue, sublist.SUOM) as InforUOM,
vi.Item, vi.[VendorBuyUOM.UOMConversion],
sublist.[Substitute Material Number], sublist.DataSource,
case when sublist.DataSource = 'Medline AutoSub' then 0
     when sublist.DataSource = 'Medline FillKill Customer Preferred' then 1
     when sublist.DataSource = 'Medline FillKill Possible Sub' then 2
     when sublist.DataSource = 'Medline PBO' then 3 end as SubRank
from sublist
left join PLMPreprocessorShared.infor.MDM_EDI_SUB_UOM [uom]
on sublist.SUOM = uom.ExternalValue
left join vi
on sublist.[Medline Item] = vi.VendorItem
GO

CREATE OR ALTER VIEW [FillKill].[vw_MedlineFillKillItemCollection] as
with a as( --item in scope
  select distinct Item as [Medline Item], UM, [Customer Item #], [Mfr. Item #], [Manufacturer Name],
  InforUOM
  from [FillKill].[vw_MedlineFillKill]
 ),
 b as( --item uom qoe
 select Item, UOM, UOMConversion
 FROM PLMPreprocessorShared.infor.MDM_ITEMUOM
 ),
 c as( --contract vendor item qoe
 select *, count(1) over (partition by VendorItem order by (select null)) as UOM_QOE_VARS --if not 1, means multiple uom/qoe per vendoritem
 from
 (
 select distinct VendorItem, UOM, DerivedUOMConversion
 from PLMPreprocessorShared.infor.CONTRACTLINE [cl]
 join (select distinct Item from [FillKill].[vw_MedlineFillKill]) [medline]
 on cl.VendorItem = medline.Item
 )[inner]
 ),
 d as( -- medline sub, rank smaller -- more reliable/preferred sub
 select *,
 case when MinSubRank = 0 then 'Medline AutoSub'
      when MinSubRank = 1 then 'Medline FillKill Customer Preferred'
      when MinSubRank = 2 then 'Medline FillKill Possible Sub'
      when MinSubRank = 3 then 'Medline PBO' end as SubDataSource,
 count(1) over (partition by [Medline Item], InforUOM order by (select null)) AS SUB_VARS --if not 1, means multiple subs
 from(
     select [Medline Item], InforUOM, [Substitute Material Number], min(SubRank) as MinSubRank
     from PLM.FillKill.vw_MedlineSubList
     Group by [Medline Item], InforUOM, [Substitute Material Number]
     ) [x]
 ),
 e as( -- item description most recent unique
 select Item as [Medline Item], [Item Description]
 FROM(
 select Item, [Item Description], row_number() over (partition by Item order by [Order Date] DESC) as rk
 from [FillKill].[vw_MedlineFillKill])[T]
 WHERE RK = 1
 ),
 f as( -- vendoritem match to IM
 select *, count(1) over (partition by VendorItem order by (select null)) as INFOR_ITEM_VARS
 from(
 select distinct VendorItem, Item
 from PLMPreprocessorShared.infor.MDM_VENDORITEM
 where VendorName like '%Medline%' and Active = 'Yes') [t]
 ),
 g as( -- item properties
 select Item, Active as [Item.Active], [Description] as [Item.Description], [Description3] as [Item.LongDescription],
 CommodityCode, [CommodityCode.CcDescription] as [CommodityCode.Description],
 ManufacturerNumber
 from PLMPreprocessorShared.infor.MDM_ITEM
 ),
 h as( --inactive vendor item from medline
 select distinct VendorItem, Item, Active
 from PLMPreprocessorShared.infor.MDM_VENDORITEM
 where VendorName like '%Medline%' and Active = 'No'
 )

 select a.*, g2.ManufacturerNumber as InforManufacturerNumberByCustomerItem,
 g2.[Item.Active] as InforItemActiveByCustomerItem,
 coalesce(h.Active, 'Yes') as InforVendorItemActiveByMedlineItem,
 d.[Substitute Material Number] as [Medline.Sub], d.SUB_VARS,
 d.MinSubRank as [Medline.SubRank], d.SubDataSource as [Medline.SubDataSource], --the sub's best source; 14 reads the rank
 e.[Item Description],
 f.Item as [Infor Item], f.INFOR_ITEM_VARS, --this is the matched item based vendor item, medline's customer item might not be correct
 iif(f.Item = a.[Customer Item #], 1,0) as [Infor Item Consistency],
 b.UOMConversion as [Item.UOMConversion],
 c.DerivedUOMConversion as [VendorItem.UOMConversion],
 c.UOM_QOE_VARS,
 g.[Item.Active] as [Item.Active],
 g.[Item.Description], g.[Item.LongDescription], g.[CommodityCode], g.[CommodityCode.Description]
 from a
 left join c
 on a.[Medline Item] = c.VendorItem
 left join d
 on a.[Medline Item] = d.[Medline Item]
 and a.inforUOM = d.inforUOM
 left join e
 on a.[Medline Item] = e.[Medline Item]
 left join f
 on a.[Medline Item] = f.VendorItem
 left join b
 on f.Item = b.Item
 and a.inforUOM = b.UOM
 left join g
 on f.Item = g.Item
 left join g as g2
 on a.[Customer Item #] = g2.Item
 left join h
 on a.[Medline Item] = h.VendorItem
 and a.[Customer Item #] = h.Item
GO

CREATE OR ALTER VIEW [FillKill].[vw_MedlineFillKillQtyAgg] as

select [Order Date], [Sold-To], [Sold-To Name],
[Medline Item], UM, [Customer Item #], [Mfr. Item #], [Manufacturer Name],
[Total Ordered Qty], [Total Filled Qty], ([Total Ordered Qty] - [Total Filled Qty]) [Total Killed Qty],
[Total PO Line Count]
from(
select [Order Date], [Sold-To], [Sold-To Name],
Item as [Medline Item], UM, [Customer Item #], [Mfr. Item #], [Manufacturer Name],
sum([Order Qty]) [Total Ordered Qty], sum([Filled Qty]) [Total Filled Qty],
count(1) as [Total PO Line Count]
from [FillKill].[vw_MedlineFillKill]
Group by [Order Date], [Sold-To], [Sold-To Name], Item,
UM, [Customer Item #], [Mfr. Item #], [Manufacturer Name]
)[t]
GO

-- Still in a transaction here? (SSMS's "SET IMPLICIT_TRANSACTIONS" option, or a BEGIN TRAN run
-- earlier in this window.) Then what this script changed isn't saved yet, and other sessions wait
-- on the tables it changed (SSMS's Object Explorer too: "Lock request time out period exceeded").
IF @@TRANCOUNT > 0
BEGIN
    DECLARE @open_transactions INT = @@TRANCOUNT;
    RAISERROR('%d transaction(s) still open in this window: the changes made in it are not saved yet, and other sessions wait on those tables. Run COMMIT to keep them (ROLLBACK undoes them).', 16, 1, @open_transactions);
END;
GO
