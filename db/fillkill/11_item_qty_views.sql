-- The item and quantity views behind the Fill/Kill main table, reading kill lines from
-- FillKill.vw_MedlineFillKill (10_kill_lines.sql) so the test copies show up too.
-- Run on O2, database PLM, after 10_kill_lines.sql. Safe to re-run.
--
-- Written on O2 by the module owner; copied here on 2026-10-13 so they are versioned with the
-- app. The only change from O2 is the source: FillKill.vw_MedlineFillKill instead of
-- SCSFileIngestor.MedlineFillKill.MedlineFillKill. If you change a view on O2, change it here too.
--
--   vw_MedlineFillKillItemCollection  one row per Medline item (and UM): description, Infor UOM
--                                     conversions, Medline PBO sub, Infor item cross-check
--   vw_MedlineFillKillQtyAgg          per order date x Sold-To x Medline item: ordered, filled,
--                                     killed quantities and PO line count

SET NOCOUNT ON;
GO

CREATE OR ALTER VIEW [FillKill].[vw_MedlineFillKillItemCollection] as
with a as( --item in scope
  select distinct Item as [Medline Item], UM, [Customer Item #], [Mfr. Item #], [Manufacturer Name]
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
 d as( -- medline sub
 select [Medline Item], [SUOM], [Parent Item], [Substitute Material Number],
 count(1) over (partition by [Medline Item], [SUOM] order by (select null)) AS SUB_VARS --if not 1, means multiple subs
 from SCSFileIngestor.MedlinePBO.MedlineSubCollection
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
 )

 select a.*, b.UOMConversion as [Item.UOMConversion], 
 c.DerivedUOMConversion as [VendorItem.UOMConversion], 
 c.UOM_QOE_VARS, 
 d.[Substitute Material Number] as [Medline.Sub], d.[Parent Item] as [Medline.ParentItem], d.SUB_VARS,
 e.[Item Description],
 f.Item as [Infor Item], f.INFOR_ITEM_VARS,
 iif(f.Item = a.[Customer Item #], 1,0) as [Infor Item Consistency]
 from a
 left join b
 on a.[Customer Item #] = b.Item
 and a.UM = b.UOM
 left join c
 on a.[Medline Item] = c.VendorItem
 left join d
 on a.[Medline Item] = d.[Medline Item]
 and a.um = d.SUOM
 left join e
 on a.[Medline Item] = e.[Medline Item]
 left join f
 on a.[Medline Item] = f.VendorItem
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
