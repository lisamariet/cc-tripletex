# Tripletex API — Relevant Endpoints for Competition
Extracted from OpenAPI spec. Only competition-relevant categories.

## attestation_company_modules
- GET /attestation/companyModules — Get attestation company modules

## bank/reconciliation/paymentType
- GET /bank/reconciliation/paymentType — Find payment type corresponding with sent data.
- GET /bank/reconciliation/paymentType/{id} — Get payment type by ID.

## company
- PUT /company — Update company information.
- GET /company/>withLoginAccess — Returns client customers (with accountant/auditor relation) where the current user has login access (proxy login).
- GET /company/divisions — [DEPRECATED] Find divisions.
- GET /company/{id} — Find company by ID.

## company/altinn
- GET /company/settings/altinn — Find Altinn id for login in company.
- PUT /company/settings/altinn — Update AltInn id and password.

## company/salesmodules
- GET /company/salesmodules — [BETA] Get active sales modules.
- POST /company/salesmodules — [BETA] Add (activate) a new sales module.

## company/settings/altinn
- GET /company/settings/altinn — Find Altinn id for login in company.
- PUT /company/settings/altinn — Update AltInn id and password.

## contact
- GET /contact — Find contacts corresponding with sent data.
- POST /contact — Create contact.
- POST /contact/list — Create multiple contacts.
- DELETE /contact/list — [BETA] Delete multiple contacts.
- GET /contact/{id} — Get contact by ID.
- PUT /contact/{id} — Update contact.

## country
- GET /country — Find countries corresponding with sent data.
- GET /country/{id} — Get country by ID.

## currency
- GET /currency — Find currencies corresponding with sent data.
- GET /currency/{fromCurrencyID}/exchangeRate — Returns the amount in the company currency, where the input amount is in fromCurrency, using the newest exchange rate available for the given date
- GET /currency/{fromCurrencyID}/{toCurrencyID}/exchangeRate — Returns the amount in the specified currency, where the input amount is in fromCurrency, using the newest exchange rate available for the given date
- GET /currency/{id} — Get currency by ID.
- GET /currency/{id}/rate — Find currency exchange rate corresponding with sent data.

## customer
- GET /customer — Find customers corresponding with sent data.
- POST /customer — Create customer. Related customer addresses may also be created.
- PUT /customer/list — [BETA] Update multiple customers. Addresses can also be updated.
- POST /customer/list — [BETA] Create multiple customers. Related supplier addresses may also be created.
- GET /customer/{id} — Get customer by ID.
- PUT /customer/{id} — Update customer. 
- DELETE /customer/{id} — [BETA] Delete customer by ID

## customer/category
- GET /customer/category — Find customer/supplier categories corresponding with sent data.
- POST /customer/category — Add new customer/supplier category.
- GET /customer/category/{id} — Find customer/supplier category by ID.
- PUT /customer/category/{id} — Update customer/supplier category.

## department
- GET /department — Find department corresponding with sent data.
- POST /department — Add new department.
- PUT /department/list — Update multiple departments.
- POST /department/list — Register new departments.
- GET /department/query — Wildcard search.
- GET /department/{id} — Get department by ID.
- PUT /department/{id} — Update department.
- DELETE /department/{id} — Delete department by ID

## employee
- GET /employee — Find employees corresponding with sent data.
- POST /employee — Create one employee.
- POST /employee/list — Create several employees.
- GET /employee/searchForEmployeesAndContacts — Get employees and contacts by parameters. Include contacts by default.
- GET /employee/{id} — Get employee by ID.
- PUT /employee/{id} — Update employee.

## employee/category
- GET /employee/category — Find employee category corresponding with sent data.
- POST /employee/category — Create a new employee category.
- PUT /employee/category/list — Update multiple employee categories.
- POST /employee/category/list — Create new employee categories.
- DELETE /employee/category/list — Delete multiple employee categories
- GET /employee/category/{id} — Get employee category by ID.
- PUT /employee/category/{id} — Update employee category information.
- DELETE /employee/category/{id} — Delete employee category by ID

## employee/employment
- GET /employee/employment — Find all employments for employee.
- POST /employee/employment — Create employment.
- GET /employee/employment/{id} — Find employment by ID.
- PUT /employee/employment/{id} — Update employemnt. 

## employee/employment/details
- GET /employee/employment/details — Find all employmentdetails for employment.
- POST /employee/employment/details — Create employment details.
- GET /employee/employment/details/{id} — Find employment details by ID.
- PUT /employee/employment/details/{id} — Update employment details. 

## employee/employment/employmentType
- GET /employee/employment/employmentType — Find all employment type IDs.
- GET /employee/employment/employmentType/employmentEndReasonType — Find all employment end reason type IDs.
- GET /employee/employment/employmentType/employmentFormType — Find all employment form type IDs.
- GET /employee/employment/employmentType/maritimeEmploymentType — Find all maritime employment type IDs.
- GET /employee/employment/employmentType/salaryType — Find all salary type IDs.
- GET /employee/employment/employmentType/scheduleType — Find all schedule type IDs.

## employee/employment/leaveOfAbsence
- GET /employee/employment/leaveOfAbsence — Find all leave of absence corresponding with the sent data.
- POST /employee/employment/leaveOfAbsence — Create leave of absence.
- POST /employee/employment/leaveOfAbsence/list — Create multiple leave of absences.
- GET /employee/employment/leaveOfAbsence/{id} — Find leave of absence by ID.
- PUT /employee/employment/leaveOfAbsence/{id} — Update leave of absence.

## employee/employment/leaveOfAbsenceType
- GET /employee/employment/leaveOfAbsenceType — Find all leave of absence type IDs.

## employee/employment/occupationCode
- GET /employee/employment/occupationCode — Find all profession codes.
- GET /employee/employment/occupationCode/{id} — Get occupation by ID.

## employee/employment/remunerationType
- GET /employee/employment/remunerationType — Find all remuneration type IDs.

## employee/employment/workingHoursScheme
- GET /employee/employment/workingHoursScheme — Find working hours scheme ID.

## employee/entitlement
- GET /employee/entitlement — Find all entitlements for user.
- PUT /employee/entitlement/:grantClientEntitlementsByTemplate — [BETA] Update employee entitlements in client account.
- PUT /employee/entitlement/:grantEntitlementsByTemplate — [BETA] Update employee entitlements.
- GET /employee/entitlement/client — [BETA] Find all entitlements at client for user.
- GET /employee/entitlement/{id} — Get entitlement by ID.

## employee/hourlyCostAndRate
- GET /employee/hourlyCostAndRate — Find all hourly cost and rates for employee.
- POST /employee/hourlyCostAndRate — Create hourly cost and rate.
- GET /employee/hourlyCostAndRate/{id} — Find hourly cost and rate by ID.
- PUT /employee/hourlyCostAndRate/{id} — Update hourly cost and rate. 

## employee/nextOfKin
- GET /employee/nextOfKin — Find all next of kin for employee.
- POST /employee/nextOfKin — Create next of kin.
- GET /employee/nextOfKin/{id} — Find next of kin by ID.
- PUT /employee/nextOfKin/{id} — Update next of kin. 

## employee/preferences
- GET /employee/preferences — Find employee preferences corresponding with sent data.
- PUT /employee/preferences/:changeLanguage — Change current employees language to the given language
- GET /employee/preferences/>loggedInEmployeePreferences — Get employee preferences for current user
- PUT /employee/preferences/list — Update multiple employee preferences.
- PUT /employee/preferences/{id} — Update employee preferences information.

## employee/standardTime
- GET /employee/standardTime — Find all standard times for employee.
- POST /employee/standardTime — Create standard time.
- GET /employee/standardTime/byDate — Find standard time for employee by date.
- GET /employee/standardTime/{id} — Find standard time by ID.
- PUT /employee/standardTime/{id} — Update standard time. 

## incomingInvoice
- POST /incomingInvoice — [BETA] create an invoice
- GET /incomingInvoice/search — [BETA] Get a list of invoices
- GET /incomingInvoice/{voucherId} — [BETA] Get an invoice by voucherId
- PUT /incomingInvoice/{voucherId} — [BETA] update an invoice by voucherId
- POST /incomingInvoice/{voucherId}/addPayment — [BETA] create a payment for voucher/invoice

## inventory/stocktaking/productline
- GET /inventory/stocktaking/productline — Find all order lines by stocktaking ID.
- POST /inventory/stocktaking/productline — Create order line. When creating several order lines, use /list for better performance.
- GET /inventory/stocktaking/productline/{id} — Get order line by ID.
- PUT /inventory/stocktaking/productline/{id} — Update order line.
- DELETE /inventory/stocktaking/productline/{id} — Delete order line.
- PUT /inventory/stocktaking/productline/{id}/:changeLocation — [Beta] Change location on order line.

## invoice
- GET /invoice — Find invoices corresponding with sent data. Includes charged outgoing invoices only.
- POST /invoice — Create invoice. Related Order and OrderLines can be created first, or included as new objects inside the Invoice.
- POST /invoice/list — [BETA] Create multiple invoices. Max 100 at a time.
- GET /invoice/{id} — Get invoice by ID.
- PUT /invoice/{id}/:createCreditNote — Creates a new Invoice representing a credit memo that nullifies the given invoice. Updates this invoice and any pre-existing inverse invoice.
- PUT /invoice/{id}/:createReminder — Create invoice reminder and sends it by the given dispatch type. Supports the reminder types SOFT_REMINDER, REMINDER and NOTICE_OF_DEBT_COLLECTION. DispatchType NETS_PRINT must have type NOTICE_OF_DEBT_COLLECTION. SMS and NETS_PRINT must be activated prior to usage in the API.
- PUT /invoice/{id}/:payment — Update invoice. The invoice is updated with payment information. The amount is in the invoice’s currency.
- PUT /invoice/{id}/:send — Send invoice by ID and sendType. Optionally override email recipient.
- GET /invoice/{invoiceId}/pdf — Get invoice document by invoice ID.

## invoice/details
- GET /invoice/details — Find ProjectInvoiceDetails corresponding with sent data.
- GET /invoice/details/{id} — Get ProjectInvoiceDetails by ID.

## invoice/paymentType
- GET /invoice/paymentType — Find payment type corresponding with sent data.
- GET /invoice/paymentType/{id} — Get payment type by ID.

## invoiceRemark
- GET /invoiceRemark/{id} — Get invoice remark by ID.

## ledger
- GET /ledger — Get ledger (hovedbok).
- GET /ledger/openPost — Find open posts corresponding with sent data.

## ledger/account
- GET /ledger/account — Find accounts corresponding with sent data.
- POST /ledger/account — Create a new account.
- PUT /ledger/account/list — Update multiple accounts.
- POST /ledger/account/list — Create several accounts.
- DELETE /ledger/account/list — Delete multiple accounts.
- GET /ledger/account/{id} — Get account by ID.
- PUT /ledger/account/{id} — Update account.
- DELETE /ledger/account/{id} — Delete account.

## ledger/accountingDimensionName
- GET /ledger/accountingDimensionName — Get all accounting dimension names.
- POST /ledger/accountingDimensionName — Create a new free (aka 'user defined') accounting dimension
- GET /ledger/accountingDimensionName/search — Search for accounting dimension names according to criteria.
- GET /ledger/accountingDimensionName/{id} — Get a single accounting dimension name by ID
- PUT /ledger/accountingDimensionName/{id} — Update an accounting dimension
- DELETE /ledger/accountingDimensionName/{id} — Delete an accounting dimension name by ID

## ledger/accountingDimensionValue
- POST /ledger/accountingDimensionValue — Create a new value for one of the free (aka 'user defined') accounting dimensions
- PUT /ledger/accountingDimensionValue/list — Update accounting dimension values
- GET /ledger/accountingDimensionValue/search — Search for accounting dimension values according to criteria.
- GET /ledger/accountingDimensionValue/{id} — Find accounting dimension values by ID.
- DELETE /ledger/accountingDimensionValue/{id} — Delete an accounting dimension value.  Values that have been used in postings can not be deleted.

## ledger/accountingPeriod
- GET /ledger/accountingPeriod — Find accounting periods corresponding with sent data.
- GET /ledger/accountingPeriod/{id} — Get accounting period by ID.

## ledger/annualAccount
- GET /ledger/annualAccount — Find annual accounts corresponding with sent data.
- GET /ledger/annualAccount/{id} — Get annual account by ID.

## ledger/closeGroup
- GET /ledger/closeGroup — Find close groups corresponding with sent data.
- GET /ledger/closeGroup/{id} — Get close group by ID.

## ledger/paymentTypeOut
- GET /ledger/paymentTypeOut — [BETA] Gets payment types for outgoing payments
- POST /ledger/paymentTypeOut — [BETA] Create new payment type for outgoing payments
- PUT /ledger/paymentTypeOut/list — [BETA] Update multiple payment types for outgoing payments at once
- POST /ledger/paymentTypeOut/list — [BETA] Create multiple payment types for outgoing payments at once
- GET /ledger/paymentTypeOut/{id} — [BETA] Get payment type for outgoing payments by ID.
- PUT /ledger/paymentTypeOut/{id} — [BETA] Update existing payment type for outgoing payments
- DELETE /ledger/paymentTypeOut/{id} — [BETA] Delete payment type for outgoing payments by ID.

## ledger/posting
- GET /ledger/posting — Find postings corresponding with sent data.
- PUT /ledger/posting/:closePostings — Close postings.
- GET /ledger/posting/openPost — Find open posts corresponding with sent data.
- GET /ledger/posting/{id} — Find postings by ID.

## ledger/postingByDate
- GET /ledger/postingByDate — Get postings by date range with pagination. Returns the same PostingDTO as /ledger/posting. Simplified endpoint for better performance. Fields and Changes are not supported. Token must have access to all vouchers in the company, otherwise a validation error is returned. If access control for salary information is activated, the token must have access to salary information as well.

## ledger/postingRules
- GET /ledger/postingRules — Get posting rules for current company.  The posting rules defined which accounts from the chart of accounts that are used for postings when the system creates postings.

## ledger/vatSettings
- GET /ledger/vatSettings — Get VAT settings for the logged in company.
- PUT /ledger/vatSettings — Update VAT settings for the logged in company.

## ledger/vatType
- GET /ledger/vatType — Find vat types corresponding with sent data.
- PUT /ledger/vatType/createRelativeVatType — Create a new relative VAT Type. These are used if the company has 'forholdsmessig fradrag for inngående MVA'.
- GET /ledger/vatType/{id} — Get vat type by ID.

## ledger/voucher
- GET /ledger/voucher — Find vouchers corresponding with sent data.
- POST /ledger/voucher — Add new voucher. IMPORTANT: Also creates postings. Only the gross amounts will be used. Amounts should be rounded to 2 decimals.
- GET /ledger/voucher/>externalVoucherNumber — Find vouchers based on the external voucher number.
- GET /ledger/voucher/>nonPosted — Find non-posted vouchers.
- GET /ledger/voucher/>voucherReception — Find vouchers in voucher reception.
- POST /ledger/voucher/importDocument — Upload a document to create one or more vouchers. Valid document formats are PDF, PNG, JPEG and TIFF. EHF/XML is possible with agreement with Tripletex. Send as multipart form.
- POST /ledger/voucher/importGbat10 — Import GBAT10. Send as multipart form.
- PUT /ledger/voucher/list — Update multiple vouchers. Postings with guiRow==0 will be deleted and regenerated.
- GET /ledger/voucher/{id} — Get voucher by ID.
- PUT /ledger/voucher/{id} — Update voucher. Postings with guiRow==0 will be deleted and regenerated.
- DELETE /ledger/voucher/{id} — Delete voucher by ID.
- PUT /ledger/voucher/{id}/:reverse — Reverses the voucher, and returns the reversed voucher. Supports reversing most voucher types, except salary transactions.
- PUT /ledger/voucher/{id}/:sendToInbox — Send voucher to inbox.
- PUT /ledger/voucher/{id}/:sendToLedger — Send voucher to ledger.
- GET /ledger/voucher/{id}/options — Returns a data structure containing meta information about operations that are available for this voucher. Currently only implemented for DELETE: It is possible to check if the voucher is deletable.
- POST /ledger/voucher/{voucherId}/attachment — Upload attachment to voucher. If the voucher already has an attachment the content will be appended to the existing attachment as new PDF page(s). Valid document formats are PDF, PNG, JPEG and TIFF. Non PDF formats will be converted to PDF. Send as multipart form.
- DELETE /ledger/voucher/{voucherId}/attachment — Delete attachment.
- GET /ledger/voucher/{voucherId}/pdf — Get PDF representation of voucher by ID.
- POST /ledger/voucher/{voucherId}/pdf/{fileName} — [DEPRECATED] Use POST ledger/voucher/{voucherId}/attachment instead.

## ledger/voucher/historical
- PUT /ledger/voucher/historical/:closePostings — [BETA] Close postings.
- PUT /ledger/voucher/historical/:reverseHistoricalVouchers — [BETA] Deletes all historical vouchers. Requires the "All vouchers" and "Advanced Voucher" permissions.
- POST /ledger/voucher/historical/employee — [BETA] Create one employee, based on import from external system. Validation is less strict, ie. employee department isn't required.
- POST /ledger/voucher/historical/historical — API endpoint for creating historical vouchers. These are vouchers created outside Tripletex, and should be from closed accounting years. The intended usage is to get access to historical transcations in Tripletex. Also creates postings. All amount fields in postings will be used. VAT postings must be included, these are not generated automatically like they are for normal vouchers in Tripletex. Requires the \"All vouchers\" and \"Advanced Voucher\" permissions.
- POST /ledger/voucher/historical/{voucherId}/attachment — Upload attachment to voucher. If the voucher already has an attachment the content will be appended to the existing attachment as new PDF page(s). Valid document formats are PDF, PNG, JPEG and TIFF. Non PDF formats will be converted to PDF. Send as multipart form.

## ledger/voucher/openingBalance
- GET /ledger/voucher/openingBalance — [BETA] Get the voucher for the opening balance.
- POST /ledger/voucher/openingBalance — [BETA] Add an opening balance on the given date.  All movements before this date will be 'zeroed out' in a separate correction voucher. The opening balance must have the first day of a month as the date, and it's also recommended to have the first day of the year as the date. If the postings provided don't balance the voucher, the difference will automatically be posted to a help account
- DELETE /ledger/voucher/openingBalance — [BETA] Delete the opening balance. The correction voucher will also be deleted
- GET /ledger/voucher/openingBalance/>correctionVoucher — [BETA] Get the correction voucher for the opening balance.

## ledger/voucherType
- GET /ledger/voucherType — Find voucher types corresponding with sent data.
- GET /ledger/voucherType/{id} — Get voucher type by ID.

## order
- GET /order — Find orders corresponding with sent data.
- POST /order — Create order.
- PUT /order/:invoiceMultipleOrders — [BETA] Charges a single customer invoice from multiple orders. The orders must be to the same customer, currency, due date, receiver email, attn. and smsNotificationNumber
- POST /order/list — [BETA] Create multiple Orders with OrderLines. Max 100 at a time.
- GET /order/orderConfirmation/{orderId}/pdf — Get PDF representation of order by ID.
- GET /order/packingNote/{orderId}/pdf — Get PDF representation of packing note by ID.
- PUT /order/sendInvoicePreview/{orderId} — Send Invoice Preview to customer by email.
- PUT /order/sendOrderConfirmation/{orderId} — Send Order Confirmation to customer by email.
- PUT /order/sendPackingNote/{orderId} — Send Packing Note to customer by email.
- GET /order/{id} — Get order by ID.
- PUT /order/{id} — Update order.
- DELETE /order/{id} — Delete order.
- PUT /order/{id}/:approveSubscriptionInvoice — To create a subscription invoice, first create a order with the subscription enabled, then approve it with this method. This approves the order for subscription invoicing.
- PUT /order/{id}/:attach — Attach document to specified order ID.
- PUT /order/{id}/:invoice — Create new invoice or subscription invoice from order.
- PUT /order/{id}/:unApproveSubscriptionInvoice — Unapproves the order for subscription invoicing.

## order/orderGroup
- GET /order/orderGroup — Find orderGroups corresponding with sent data.
- PUT /order/orderGroup — [Beta] Put orderGroup.
- POST /order/orderGroup — [Beta] Post orderGroup.
- GET /order/orderGroup/{id} — Get orderGroup by ID. A orderGroup is a way to group orderLines, and add comments and subtotals
- DELETE /order/orderGroup/{id} — Delete orderGroup by ID.

## order/orderline
- POST /order/orderline — Create order line. When creating several order lines, use /list for better performance.
- POST /order/orderline/list — Create multiple order lines.
- GET /order/orderline/orderLineTemplate — [BETA] Get order line template from order and product
- GET /order/orderline/{id} — Get order line by ID.
- PUT /order/orderline/{id} — [BETA] Put order line
- DELETE /order/orderline/{id} — [BETA] Delete order line by ID.
- PUT /order/orderline/{id}/:pickLine — [BETA] Pick order line. This is only available for customers who have Logistics and who activated the available inventory functionality.
- PUT /order/orderline/{id}/:unpickLine — [BETA] Unpick order line.This is only available for customers who have Logistics and who activated the available inventory functionality.

## product
- GET /product — Find products corresponding with sent data.
- POST /product — Create new product.
- PUT /product/list — Update a list of products.
- POST /product/list — Add multiple products.
- GET /product/{id} — Get product by ID.
- PUT /product/{id} — Update product.
- DELETE /product/{id} — Delete product.
- POST /product/{id}/image — Upload image to product. Existing image on product will be replaced if exists
- DELETE /product/{id}/image — Delete image.

## product/discountGroup
- GET /product/discountGroup — Find discount groups corresponding with sent data.
- GET /product/discountGroup/{id} — Get discount group by ID.

## product/external
- GET /product/external — [BETA] Find external products corresponding with sent data. The sorting-field is not in use on this endpoint.
- GET /product/external/{id} — [BETA] Get external product by ID.

## product/group
- GET /product/group — Find product group with sent data. Only available for Logistics Basic.
- POST /product/group — Create new product group. Only available for Logistics Basic.
- PUT /product/group/list — Update a list of product groups. Only available for Logistics Basic.
- POST /product/group/list — Add multiple products groups. Only available for Logistics Basic.
- DELETE /product/group/list — Delete multiple product groups. Only available for Logistics Basic.
- GET /product/group/query — Wildcard search. Only available for Logistics Basic.
- GET /product/group/{id} — Find product group by ID. Only available for Logistics Basic.
- PUT /product/group/{id} — Update product group. Only available for Logistics Basic.
- DELETE /product/group/{id} — Delete product group. Only available for Logistics Basic.

## product/groupRelation
- GET /product/groupRelation — Find product group relation with sent data. Only available for Logistics Basic.
- POST /product/groupRelation — Create new product group relation. Only available for Logistics Basic.
- POST /product/groupRelation/list — Add multiple products group relations. Only available for Logistics Basic.
- DELETE /product/groupRelation/list — Delete multiple product group relations. Only available for Logistics Basic.
- GET /product/groupRelation/{id} — Find product group relation by ID. Only available for Logistics Basic.
- DELETE /product/groupRelation/{id} — Delete product group relation. Only available for Logistics Basic.

## product/inventoryLocation
- GET /product/inventoryLocation — Find inventory locations by product ID. Only available for Logistics Basic.
- POST /product/inventoryLocation — Create new product inventory location. Only available for Logistics Basic.
- PUT /product/inventoryLocation/list — Update multiple product inventory locations. Only available for Logistics Basic.
- POST /product/inventoryLocation/list — Add multiple product inventory locations. Only available for Logistics Basic.
- GET /product/inventoryLocation/{id} — Get inventory location by ID. Only available for Logistics Basic.
- PUT /product/inventoryLocation/{id} — Update product inventory location. Only available for Logistics Basic.
- DELETE /product/inventoryLocation/{id} — Delete product inventory location. Only available for Logistics Basic.

## product/logisticsSettings
- GET /product/logisticsSettings — Get logistics settings for the logged in company.
- PUT /product/logisticsSettings — Update logistics settings for the logged in company.

## product/productPrice
- GET /product/productPrice — Find prices for a product. Only available for Logistics Basic.

## product/supplierProduct
- GET /product/supplierProduct — Find products corresponding with sent data.
- POST /product/supplierProduct — Create new supplierProduct.
- POST /product/supplierProduct/getSupplierProductsByIds — Find the products by ids. Method was added as a POST because GET request header has a maximum size that we can exceed with customers that a lot of products.
- PUT /product/supplierProduct/list — Update a list of supplierProduct.
- POST /product/supplierProduct/list — Create list of new supplierProduct.
- GET /product/supplierProduct/{id} — Get supplierProduct by ID.
- PUT /product/supplierProduct/{id} — Update supplierProduct.
- DELETE /product/supplierProduct/{id} — Delete supplierProduct.

## product/unit
- GET /product/unit — Find product units corresponding with sent data.
- POST /product/unit — Create new product unit.
- PUT /product/unit/list — Update list of product units.
- POST /product/unit/list — Create multiple product units.
- GET /product/unit/query — Wildcard search.
- GET /product/unit/{id} — Get product unit by ID.
- PUT /product/unit/{id} — Update product unit.
- DELETE /product/unit/{id} — Delete product unit by ID.

## product/unit/master
- GET /product/unit/master — Find product units master corresponding with sent data.
- GET /product/unit/master/{id} — Get product unit master by ID.

## project
- GET /project — Find projects corresponding with sent data.
- POST /project — Add new project.
- DELETE /project — [BETA] Delete multiple projects.
- GET /project/>forTimeSheet — Find projects applicable for time sheet registration on a specific day.
- POST /project/import — Upload project import file.
- PUT /project/list — [BETA] Update multiple projects.
- POST /project/list — [BETA] Register new projects. Multiple projects for different users can be sent in the same request.
- DELETE /project/list — [BETA] Delete projects.
- GET /project/number/{number} — Find project by number.
- GET /project/{id} — Find project by ID.
- PUT /project/{id} — [BETA] Update project.
- DELETE /project/{id} — [BETA] Delete project.

## project/batchPeriod
- GET /project/batchPeriod/budgetStatusByProjectIds — Get the budget status for the projects in the specific period.
- GET /project/batchPeriod/invoicingReserveByProjectIds — Get the invoicing reserve for the projects in the specific period.

## project/category
- GET /project/category — Find project categories corresponding with sent data.
- POST /project/category — Add new project category.
- GET /project/category/{id} — Find project category by ID.
- PUT /project/category/{id} — Update project category.

## project/controlForm
- GET /project/controlForm — [BETA] Get project control forms by project ID.
- GET /project/controlForm/{id} — [BETA] Get project control form by ID.

## project/controlFormType
- GET /project/controlFormType — [BETA] Get project control form types
- GET /project/controlFormType/{id} — [BETA] Get project control form type by ID.

## project/dynamicControlForm
- PUT /project/dynamicControlForm/{id}/:copyFieldValuesFromLastEditedForm — Into each section in the specified form that only has empty or default values, and copyFieldValuesByDefault set as true in the form's template, copy field values from the equivalent section in the most recently edited control form. Signed or completed forms will not be affected.

## project/hourlyRates
- GET /project/hourlyRates — Find project hourly rates corresponding with sent data.
- POST /project/hourlyRates — Create a project hourly rate. 
- DELETE /project/hourlyRates/deleteByProjectIds — Delete project hourly rates by project id.
- PUT /project/hourlyRates/list — Update multiple project hourly rates.
- POST /project/hourlyRates/list — Create multiple project hourly rates.
- DELETE /project/hourlyRates/list — Delete project hourly rates.
- PUT /project/hourlyRates/updateOrAddHourRates — Update or add the same project hourly rate from project overview.
- GET /project/hourlyRates/{id} — Find project hourly rate by ID.
- PUT /project/hourlyRates/{id} — Update a project hourly rate.
- DELETE /project/hourlyRates/{id} — Delete Project Hourly Rate 

## project/hourlyRates/projectSpecificRates
- GET /project/hourlyRates/projectSpecificRates — Find project specific rates corresponding with sent data.
- POST /project/hourlyRates/projectSpecificRates — Create new project specific rate. 
- PUT /project/hourlyRates/projectSpecificRates/list — Update multiple project specific rates.
- POST /project/hourlyRates/projectSpecificRates/list — Create multiple new project specific rates.
- DELETE /project/hourlyRates/projectSpecificRates/list — Delete project specific rates.
- GET /project/hourlyRates/projectSpecificRates/{id} — Find project specific rate by ID.
- PUT /project/hourlyRates/projectSpecificRates/{id} — Update a project specific rate.
- DELETE /project/hourlyRates/projectSpecificRates/{id} — Delete project specific rate 

## project/import
- POST /project/import — Upload project import file.

## project/orderline
- GET /project/orderline — [BETA] Find all order lines for project.
- POST /project/orderline — [BETA] Create order line. When creating several order lines, use /list for better performance.
- POST /project/orderline/list — [BETA] Create multiple order lines.
- GET /project/orderline/orderLineTemplate — [BETA] Get order line template from project and product
- GET /project/orderline/query — [BETA] Wildcard search.
- GET /project/orderline/{id} — [BETA] Get order line by ID.
- PUT /project/orderline/{id} — [BETA] Update project orderline.
- DELETE /project/orderline/{id} — Delete order line by ID.

## project/participant
- POST /project/participant — [BETA] Add new project participant.
- POST /project/participant/list — [BETA] Add new project participant. Multiple project participants can be sent in the same request.
- DELETE /project/participant/list — [BETA] Delete project participants.
- GET /project/participant/{id} — [BETA] Find project participant by ID.
- PUT /project/participant/{id} — [BETA] Update project participant.

## project/period
- GET /project/{id}/period/budgetStatus — Get the budget status for the project period
- GET /project/{id}/period/hourlistReport — Find hourlist report by project period.
- GET /project/{id}/period/invoiced — Find invoiced info by project period.
- GET /project/{id}/period/invoicingReserve — Find invoicing reserve by project period.
- GET /project/{id}/period/monthlyStatus — Find overall status by project period.
- GET /project/{id}/period/overallStatus — Find overall status by project period.

## project/projectActivity
- POST /project/projectActivity — Add project activity.
- DELETE /project/projectActivity/list — Delete project activities
- GET /project/projectActivity/{id} — Find project activity by id
- DELETE /project/projectActivity/{id} — Delete project activity

## project/resourcePlanBudget
- GET /project/resourcePlanBudget — Get resource plan entries in the specified period.

## project/resourceplan
- GET /project/resourcePlanBudget — Get resource plan entries in the specified period.

## project/settings
- GET /project/settings — Get project settings of logged in company.
- PUT /project/settings — Update project settings for company

## project/subcontract
- GET /project/subcontract — Find project sub-contracts corresponding with sent data.
- POST /project/subcontract — Add new project sub-contract.
- GET /project/subcontract/query — Wildcard search.
- GET /project/subcontract/{id} — Find project sub-contract by ID.
- PUT /project/subcontract/{id} — Update project sub-contract.
- DELETE /project/subcontract/{id} — Delete project sub-contract by ID.

## project/task
- GET /project/task — Find all tasks for project.

## project/template
- GET /project/template/{id} — Get project template by ID.

## project/{id}/period
- GET /project/{id}/period/budgetStatus — Get the budget status for the project period
- GET /project/{id}/period/hourlistReport — Find hourlist report by project period.
- GET /project/{id}/period/invoiced — Find invoiced info by project period.
- GET /project/{id}/period/invoicingReserve — Find invoicing reserve by project period.
- GET /project/{id}/period/monthlyStatus — Find overall status by project period.
- GET /project/{id}/period/overallStatus — Find overall status by project period.

## purchaseOrder
- GET /purchaseOrder — Find purchase orders with send data. Only available for Logistics Basic.
- POST /purchaseOrder — Creates a new purchase order. Only available for Logistics Basic.
- GET /purchaseOrder/{id} — Find purchase order by ID. Only available for Logistics Basic.
- PUT /purchaseOrder/{id} —  Update purchase order. Only available for Logistics Basic.
- DELETE /purchaseOrder/{id} —  Delete purchase order. Only available for Logistics Basic.
- PUT /purchaseOrder/{id}/:send — Send purchase order by ID and sendType. Only available for Logistics Basic.
- PUT /purchaseOrder/{id}/:sendByEmail — Send purchase order by customisable email. Only available for Logistics Basic.
- POST /purchaseOrder/{id}/attachment — Upload attachment to purchase order. Only available for Logistics Basic.
- DELETE /purchaseOrder/{id}/attachment — Delete attachment. Only available for Logistics Basic.
- POST /purchaseOrder/{id}/attachment/list — Upload multiple attachments to Purchase Order. Only available for Logistics Basic.

## purchaseOrder/deviation
- GET /purchaseOrder/deviation — Find handled deviations for purchase order. Only available for Logistics Basic.
- POST /purchaseOrder/deviation — Register deviation on goods receipt. Only available for Logistics Basic.
- PUT /purchaseOrder/deviation/list — Update multiple deviations. Only available for Logistics Basic.
- POST /purchaseOrder/deviation/list — Register multiple deviations. Only available for Logistics Basic.
- GET /purchaseOrder/deviation/{id} — Get deviation by order line ID. Only available for Logistics Basic.
- PUT /purchaseOrder/deviation/{id} — Update deviation. Only available for Logistics Basic.
- DELETE /purchaseOrder/deviation/{id} — Delete goods receipt by purchase order ID. Only available for Logistics Basic.
- PUT /purchaseOrder/deviation/{id}/:approve — Approve deviations. Only available for Logistics Basic.
- PUT /purchaseOrder/deviation/{id}/:deliver — Send deviations to approval. Only available for Logistics Basic.
- PUT /purchaseOrder/deviation/{id}/:undeliver — Set status to Not delivered for deviations. Only available for Logistics Basic.

## purchaseOrder/goodsReceipt
- GET /purchaseOrder/goodsReceipt — Get goods receipt. Only available for Logistics Basic.
- POST /purchaseOrder/goodsReceipt — Register goods receipt without an existing purchase order. When registration of several goods receipt, use /list for better performance. Only available for Logistics Basic.
- POST /purchaseOrder/goodsReceipt/list — Register multiple goods receipts without an existing purchase order. Only available for Logistics Basic.
- DELETE /purchaseOrder/goodsReceipt/list — Delete multiple goods receipts by ID. Only available for Logistics Basic.
- GET /purchaseOrder/goodsReceipt/{id} — Get goods receipt by purchase order ID. Only available for Logistics Basic.
- PUT /purchaseOrder/goodsReceipt/{id} — Update goods receipt. Only available for Logistics Basic.
- DELETE /purchaseOrder/goodsReceipt/{id} — Delete goods receipt by ID. Only available for Logistics Basic.
- PUT /purchaseOrder/goodsReceipt/{id}/:confirm — Confirm goods receipt. Only available for Logistics Basic.
- PUT /purchaseOrder/goodsReceipt/{id}/:receiveAndConfirm —  Receive all ordered products and approve goods receipt. Only available for Logistics Basic.
- PUT /purchaseOrder/goodsReceipt/{id}/:registerGoodsReceipt — Register goods receipt. Quantity received on the products is set to the same as quantity ordered. To update the quantity received, use PUT /purchaseOrder/goodsReceiptLine/{id}. Only available for Logistics Basic.

## purchaseOrder/goodsReceiptLine
- GET /purchaseOrder/goodsReceiptLine — Find goods receipt lines for purchase order. Only available for Logistics Basic.
- POST /purchaseOrder/goodsReceiptLine — Register new goods receipt; new product on an existing purchase order. When registration of several goods receipts, use /list for better performance. Only available for Logistics Basic.
- PUT /purchaseOrder/goodsReceiptLine/list — Update goods receipt lines on a goods receipt. Only available for Logistics Basic.
- POST /purchaseOrder/goodsReceiptLine/list — Register multiple new goods receipts on an existing purchase order. Only available for Logistics Basic.
- DELETE /purchaseOrder/goodsReceiptLine/list — Delete goods receipt lines by ID. Only available for Logistics Basic.
- GET /purchaseOrder/goodsReceiptLine/{id} — Get goods receipt line by purchase order line ID. Only available for Logistics Basic.
- PUT /purchaseOrder/goodsReceiptLine/{id} — Update a goods receipt line on a goods receipt. Only available for Logistics Basic.
- DELETE /purchaseOrder/goodsReceiptLine/{id} — Delete goods receipt line by ID. Only available for Logistics Basic.

## purchaseOrder/orderline
- POST /purchaseOrder/orderline — Creates purchase order line. Only available for Logistics Basic.
- PUT /purchaseOrder/orderline/list — Update a list of purchase order lines. Only available for Logistics Basic.
- POST /purchaseOrder/orderline/list — Create list of new purchase order lines. Only available for Logistics Basic.
- DELETE /purchaseOrder/orderline/list — Delete purchase order lines by ID. Only available for Logistics Basic.
- GET /purchaseOrder/orderline/{id} — Find purchase order line by ID. Only available for Logistics Basic.
- PUT /purchaseOrder/orderline/{id} — Updates purchase order line. Only available for Logistics Basic.
- DELETE /purchaseOrder/orderline/{id} — Delete purchase order line. Only available for Logistics Basic.

## purchaseOrder/purchaseOrderIncomingInvoiceRelation
- GET /purchaseOrder/purchaseOrderIncomingInvoiceRelation — Find purchase order relation to voucher with sent data. Only available for Logistics Basic.
- POST /purchaseOrder/purchaseOrderIncomingInvoiceRelation — Create new relation between purchase order and a voucher. Only available for Logistics Basic.
- POST /purchaseOrder/purchaseOrderIncomingInvoiceRelation/list — Create a new list of relations between purchase order and voucher. Only available for Logistics Basic.
- DELETE /purchaseOrder/purchaseOrderIncomingInvoiceRelation/list — Delete multiple purchase order voucher relations. Only available for Logistics Basic.
- GET /purchaseOrder/purchaseOrderIncomingInvoiceRelation/{id} — Find purchase order relation to voucher by ID. Only available for Logistics Basic.
- DELETE /purchaseOrder/purchaseOrderIncomingInvoiceRelation/{id} — Delete purchase order voucher relation. Only available for Logistics Basic.

## salary/compilation
- GET /salary/compilation — Find salary compilation by employee.
- GET /salary/compilation/pdf — Find salary compilation (PDF document) by employee.

## salary/holidayAllowance/reconciliation
- POST /salary/holidayAllowance/reconciliation/context — Create a holiday allowance reconciliation context for a customer
- GET /salary/holidayAllowance/reconciliation/{reconciliationId}/holidayAllowanceDetails — Get a holiday allowance details for the current reconciliation term
- GET /salary/holidayAllowance/reconciliation/{reconciliationId}/holidayAllowanceSummary — Salary holiday allowance reconciliation summary

## salary/mandatoryDeduction/reconciliation
- POST /salary/mandatoryDeduction/reconciliation/context — Create a mandatoryDeduction reconciliation context for a customer
- GET /salary/mandatoryDeduction/reconciliation/{reconciliationId}/overview — Salary mandatory deduction reconciliation overview
- GET /salary/mandatoryDeduction/reconciliation/{reconciliationId}/paymentsOverview — Get mandatory deduction payments overview from start of year to the current reconciliation term

## salary/payrollTax/reconciliation
- POST /salary/payrollTax/reconciliation/context — Create a payroll tax reconciliation context for a customer
- GET /salary/payrollTax/reconciliation/{reconciliationId}/overview — Salary payroll tax reconciliation overview
- GET /salary/payrollTax/reconciliation/{reconciliationId}/paymentsOverview — Get a payroll tax payments from start of year to the current reconciliation term

## salary/payslip
- GET /salary/payslip — Find payslips corresponding with sent data.
- GET /salary/payslip/{id} — Find payslip by ID.
- GET /salary/payslip/{id}/pdf — Find payslip (PDF document) by ID.

## salary/reconciliation/tax-deduction
- GET /salary/taxDeduction/reconciliation/{reconciliationId}/balanceAndOwedAmount — Get tax deduction details for a reconciliation

## salary/settings
- GET /salary/settings — Get salary settings of logged in company.
- PUT /salary/settings — Update settings of logged in company.

## salary/settings/holiday
- GET /salary/settings/holiday — Find holiday settings of current logged in company.
- POST /salary/settings/holiday — Create a holiday setting of current logged in company.
- PUT /salary/settings/holiday/list — Update multiple holiday settings of current logged in company.
- POST /salary/settings/holiday/list — Create multiple holiday settings of current logged in company.
- DELETE /salary/settings/holiday/list — Delete multiple holiday settings of current logged in company.
- PUT /salary/settings/holiday/{id} — Update a holiday setting of current logged in company.

## salary/settings/pensionScheme
- GET /salary/settings/pensionScheme — Find pension schemes.
- POST /salary/settings/pensionScheme — Create a Pension Scheme.
- PUT /salary/settings/pensionScheme/list — Update multiple Pension Schemes.
- POST /salary/settings/pensionScheme/list — Create multiple Pension Schemes.
- DELETE /salary/settings/pensionScheme/list — Delete multiple Pension Schemes.
- GET /salary/settings/pensionScheme/{id} — Get Pension Scheme for a specific ID
- PUT /salary/settings/pensionScheme/{id} — Update a Pension Scheme
- DELETE /salary/settings/pensionScheme/{id} — Delete a Pension Scheme

## salary/settings/standardTime
- GET /salary/settings/standardTime — Get all standard times.
- POST /salary/settings/standardTime — Create standard time.
- GET /salary/settings/standardTime/byDate — Find standard time by date
- GET /salary/settings/standardTime/{id} — Find standard time by ID.
- PUT /salary/settings/standardTime/{id} — Update standard time. 

## salary/taxDeduction/reconciliation
- POST /salary/taxDeduction/reconciliation/context — Create a taxDeduction reconciliation context for a customer
- GET /salary/taxDeduction/reconciliation/{reconciliationId}/balanceAndOwedAmount — Get tax deduction details for a reconciliation
- GET /salary/taxDeduction/reconciliation/{reconciliationId}/overview — Get salary tax deduction data for the reconciliation table
- GET /salary/taxDeduction/reconciliation/{reconciliationId}/paymentsOverview — Get salary tax deduction payment overview from start of year to the current reconciliation term

## salary/transaction
- POST /salary/transaction — Create a new salary transaction.
- GET /salary/transaction/{id} — Find salary transaction by ID.
- DELETE /salary/transaction/{id} — Delete salary transaction by ID.
- POST /salary/transaction/{id}/attachment — Upload an attachment to a salary transaction
- POST /salary/transaction/{id}/attachment/list — Upload multiple attachments to a salary transaction
- PUT /salary/transaction/{id}/deleteAttachment — Delete attachment.

## salary/type
- GET /salary/type — Find salary type corresponding with sent data.
- GET /salary/type/{id} — Find salary type by ID.

## supplier
- GET /supplier — Find suppliers corresponding with sent data.
- POST /supplier — Create supplier. Related supplier addresses may also be created.
- PUT /supplier/list — Update multiple suppliers. Addresses can also be updated.
- POST /supplier/list — Create multiple suppliers. Related supplier addresses may also be created.
- GET /supplier/{id} — Get supplier by ID.
- PUT /supplier/{id} — Update supplier. 
- DELETE /supplier/{id} — Delete supplier by ID

## supplierCustomer
- GET /supplierCustomer/search — Find all active suppliers and customers.

## supplierInvoice
- GET /supplierInvoice — Find supplierInvoices corresponding with sent data.
- PUT /supplierInvoice/:addRecipient — Add recipient.
- PUT /supplierInvoice/:approve — Approve supplier invoices.
- PUT /supplierInvoice/:reject — reject supplier invoices.
- GET /supplierInvoice/forApproval — Get supplierInvoices for approval
- PUT /supplierInvoice/voucher/{id}/postings — [BETA] Put debit postings.
- GET /supplierInvoice/{id} — Get supplierInvoice by ID.
- POST /supplierInvoice/{invoiceId}/:addPayment — Register payment, paymentType == 0 finds the last paymentType for this vendor.Use of this method requires setup done by Tripletex.
- PUT /supplierInvoice/{invoiceId}/:addRecipient — Add recipient to supplier invoices.
- PUT /supplierInvoice/{invoiceId}/:approve — Approve supplier invoice.
- PUT /supplierInvoice/{invoiceId}/:changeDimension — Change dimension on a supplier invoice.
- PUT /supplierInvoice/{invoiceId}/:reject — reject supplier invoice.
- GET /supplierInvoice/{invoiceId}/pdf — Get supplierInvoice document by invoice ID.

## timesheet/companyHoliday
- GET /timesheet/companyHoliday — [BETA] Search for company holidays by id or year.
- POST /timesheet/companyHoliday — [BETA] Create a company holiday
- GET /timesheet/companyHoliday/{id} — [BETA] Get company holiday by its ID
- PUT /timesheet/companyHoliday/{id} — [BETA] Update a company holiday
- DELETE /timesheet/companyHoliday/{id} — [BETA] Delete a company holiday

## timesheet/salaryProjectTypeSpecification
- GET /timesheet/salaryProjectTypeSpecification — Get list of time sheet ProjectSalaryType specifications
- POST /timesheet/salaryProjectTypeSpecification — Create a timesheet ProjectSalaryType specification
- GET /timesheet/salaryProjectTypeSpecification/{id} — Get timesheet ProjectSalaryType specification for a specific ID
- PUT /timesheet/salaryProjectTypeSpecification/{id} — Update a timesheet ProjectSalaryType specification
- DELETE /timesheet/salaryProjectTypeSpecification/{id} — Delete a timesheet SalaryType specification

## timesheet/salaryTypeSpecification
- GET /timesheet/salaryTypeSpecification — [BETA] Get list of timesheet SalaryType Specifications
- POST /timesheet/salaryTypeSpecification — [BETA] Create a timesheet SalaryType Specification. Only one entry per employee/date/SalaryType
- GET /timesheet/salaryTypeSpecification/{id} — [BETA] Get timesheet SalaryType Specification for a specific ID
- PUT /timesheet/salaryTypeSpecification/{id} — [BETA] Update a timesheet SalaryType Specification
- DELETE /timesheet/salaryTypeSpecification/{id} — [BETA] Delete a timesheet SalaryType Specification

## token/employee
- PUT /token/employee/:create — Create an employee token. Only selected consumers are allowed

## travelExpense
- GET /travelExpense — Find travel expenses corresponding with sent data.
- POST /travelExpense — Create travel expense.
- PUT /travelExpense/:approve — Approve travel expenses.
- PUT /travelExpense/:copy — Copy travel expense.
- PUT /travelExpense/:createVouchers — Create vouchers
- PUT /travelExpense/:deliver — Deliver travel expenses.
- PUT /travelExpense/:unapprove — Unapprove travel expenses.
- PUT /travelExpense/:undeliver — Undeliver travel expenses.
- GET /travelExpense/{id} — Get travel expense by ID.
- PUT /travelExpense/{id} — Update travel expense.
- DELETE /travelExpense/{id} — Delete travel expense.
- PUT /travelExpense/{id}/convert — Convert travel to/from employee expense.
- GET /travelExpense/{travelExpenseId}/attachment — Get attachment by travel expense ID.
- POST /travelExpense/{travelExpenseId}/attachment — Upload attachment to travel expense.
- DELETE /travelExpense/{travelExpenseId}/attachment — Delete attachment.
- POST /travelExpense/{travelExpenseId}/attachment/list — Upload multiple attachments to travel expense.

## travelExpense/accommodationAllowance
- GET /travelExpense/accommodationAllowance — Find accommodation allowances corresponding with sent data.
- POST /travelExpense/accommodationAllowance — Create accommodation allowance.
- GET /travelExpense/accommodationAllowance/{id} — Get travel accommodation allowance by ID.
- PUT /travelExpense/accommodationAllowance/{id} — Update accommodation allowance.
- DELETE /travelExpense/accommodationAllowance/{id} — Delete accommodation allowance.

## travelExpense/cost
- GET /travelExpense/cost — Find costs corresponding with sent data.
- POST /travelExpense/cost — Create cost.
- PUT /travelExpense/cost/list — Update costs.
- GET /travelExpense/cost/{id} — Get cost by ID.
- PUT /travelExpense/cost/{id} — Update cost.
- DELETE /travelExpense/cost/{id} — Delete cost.

## travelExpense/costCategory
- GET /travelExpense/costCategory — Find cost category corresponding with sent data.
- GET /travelExpense/costCategory/{id} — Get cost category by ID.

## travelExpense/costParticipant
- POST /travelExpense/costParticipant — Create participant on cost.
- POST /travelExpense/costParticipant/createCostParticipantAdvanced — Create participant on cost using explicit parameters
- POST /travelExpense/costParticipant/list — Create participants on cost.
- DELETE /travelExpense/costParticipant/list — Delete cost participants.
- GET /travelExpense/costParticipant/{costId}/costParticipants — Get cost's participants by costId.
- GET /travelExpense/costParticipant/{id} — Get cost participant by ID.
- DELETE /travelExpense/costParticipant/{id} — Delete cost participant.

## travelExpense/drivingStop
- POST /travelExpense/drivingStop — Create mileage allowance driving stop.
- GET /travelExpense/drivingStop/{id} — Get driving stop by ID.
- DELETE /travelExpense/drivingStop/{id} — Delete mileage allowance stops.

## travelExpense/mileageAllowance
- GET /travelExpense/mileageAllowance — Find mileage allowances corresponding with sent data.
- POST /travelExpense/mileageAllowance — Create mileage allowance.
- GET /travelExpense/mileageAllowance/{id} — Get mileage allowance by ID.
- PUT /travelExpense/mileageAllowance/{id} — Update mileage allowance.
- DELETE /travelExpense/mileageAllowance/{id} — Delete mileage allowance.

## travelExpense/passenger
- GET /travelExpense/passenger — Find passengers corresponding with sent data.
- POST /travelExpense/passenger — Create passenger.
- POST /travelExpense/passenger/list — Create passengers.
- DELETE /travelExpense/passenger/list — Delete passengers.
- GET /travelExpense/passenger/{id} — Get passenger by ID.
- PUT /travelExpense/passenger/{id} — Update passenger.
- DELETE /travelExpense/passenger/{id} — Delete passenger.

## travelExpense/paymentType
- GET /travelExpense/paymentType — Find payment type corresponding with sent data.
- GET /travelExpense/paymentType/{id} — Get payment type by ID.

## travelExpense/perDiemCompensation
- GET /travelExpense/perDiemCompensation — Find per diem compensations corresponding with sent data.
- POST /travelExpense/perDiemCompensation — Create per diem compensation.
- GET /travelExpense/perDiemCompensation/{id} — Get per diem compensation by ID.
- PUT /travelExpense/perDiemCompensation/{id} — Update per diem compensation.
- DELETE /travelExpense/perDiemCompensation/{id} — Delete per diem compensation.

## travelExpense/rate
- GET /travelExpense/rate — Find rates corresponding with sent data.
- GET /travelExpense/rate/{id} — Get travel expense rate by ID.

## travelExpense/rateCategory
- GET /travelExpense/rateCategory — Find rate categories corresponding with sent data.
- GET /travelExpense/rateCategory/{id} — Get travel expense rate category by ID.

## travelExpense/rateCategoryGroup
- GET /travelExpense/rateCategoryGroup — Find rate categoriy groups corresponding with sent data.
- GET /travelExpense/rateCategoryGroup/{id} — Get travel report rate category group by ID.

## travelExpense/settings
- GET /travelExpense/settings — Get travel expense settings of logged in company.

## travelExpense/zone
- GET /travelExpense/zone — Find travel expense zones corresponding with sent data.
- GET /travelExpense/zone/{id} — Get travel expense zone by ID.

## voucherApprovalListElement
- GET /voucherApprovalListElement/{id} — Get by ID.

## voucherInbox
- GET /voucherInbox/inboxCount — Get count of items in the Voucher Inbox

## voucherMessage
- GET /voucherMessage — [BETA] Find voucherMessage (or a comment) put on a voucher by inputting voucher ids
- POST /voucherMessage — [BETA] Post new voucherMessage.

## voucherStatus
- GET /voucherStatus — Find voucherStatus corresponding with sent data. The voucherStatus is used to coordinate integration processes. Requires setup done by Tripletex, currently supports debt collection.
- POST /voucherStatus — Post new voucherStatus.
- GET /voucherStatus/{id} — Get voucherStatus by ID.

---
## All API tags (190 total)
accountantDashboard/news, accountingDimensionName, accountingDimensionValue, accountingOffice/reconciliations, accountingOffice/reconciliations/{reconciliationId}/control, accountingOffice/reconciliations/{reconciliationId}/control/:controlReconciliation, accountingOffice/reconciliations/{reconciliationId}/control/:reconcile, accountingOffice/reconciliations/{reconciliationId}/control/:requestControl, activity, asset, attestation, attestation_company_modules, balance/reconciliation, balanceSheet, bank, bank/reconciliation, bank/reconciliation/match, bank/reconciliation/matches/counter, bank/reconciliation/paymentType, bank/reconciliation/settings, bank/statement, bank/statement/transaction, company, company/altinn, company/salesmodules, company/settings/altinn, contact, country, crm/prospect, currency, customer, customer/category, debtCollector/internal, deliveryAddress, department, division, document, documentArchive, employee, employee/category, employee/employment, employee/employment/details, employee/employment/employmentType, employee/employment/leaveOfAbsence, employee/employment/leaveOfAbsenceType, employee/employment/occupationCode, employee/employment/remunerationType, employee/employment/workingHoursScheme, employee/entitlement, employee/hourlyCostAndRate, employee/nextOfKin, employee/preferences, employee/standardTime, event, event/subscription, financeTax/reconciliation, incomingInvoice, internal, internal/debtCollector, internal/nhoAdmin, inventory, inventory/inventories, inventory/location, inventory/stocktaking, inventory/stocktaking/productline, invoice, invoice/details, invoice/paymentType, invoiceRemark, ledger, ledger/account, ledger/accountingDimensionName, ledger/accountingDimensionValue, ledger/accountingPeriod, ledger/annualAccount, ledger/closeGroup, ledger/paymentTypeOut, ledger/posting, ledger/postingByDate, ledger/postingRules, ledger/vatSettings, ledger/vatType, ledger/voucher, ledger/voucher/historical, ledger/voucher/openingBalance, ledger/voucherType, municipality, order, order/orderGroup, order/orderline, penneo, pension, pickupPoint, platformAgnostic/bank/onboarding, product, product/discountGroup, product/external, product/group, product/groupRelation, product/inventoryLocation, product/logisticsSettings, product/productPrice, product/supplierProduct, product/unit, product/unit/master, project, project/batchPeriod, project/category, project/controlForm, project/controlFormType, project/dynamicControlForm, project/hourlyRates, project/hourlyRates/projectSpecificRates, project/import, project/orderline, project/participant, project/period, project/projectActivity, project/resourcePlanBudget, project/resourceplan, project/settings, project/subcontract, project/task, project/template, project/{id}/period, purchaseOrder, purchaseOrder/deviation, purchaseOrder/goodsReceipt, purchaseOrder/goodsReceiptLine, purchaseOrder/orderline, purchaseOrder/purchaseOrderIncomingInvoiceRelation, reminder, researchAndDevelopment2024, resultbudget, saft, salary/compilation, salary/holidayAllowance/reconciliation, salary/mandatoryDeduction/reconciliation, salary/payrollTax/reconciliation, salary/payslip, salary/reconciliation/tax-deduction, salary/settings, salary/settings/holiday, salary/settings/pensionScheme, salary/settings/standardTime, salary/taxDeduction/reconciliation, salary/transaction, salary/type, subscription, supplier, supplierCustomer, supplierInvoice, supportDashboard, timesheet/allocated, timesheet/companyHoliday, timesheet/entry, timesheet/month, timesheet/salaryProjectTypeSpecification, timesheet/salaryTypeSpecification, timesheet/settings, timesheet/timeClock, timesheet/week, token/consumer, token/employee, token/session, transportType, travelExpense, travelExpense/accommodationAllowance, travelExpense/cost, travelExpense/costCategory, travelExpense/costParticipant, travelExpense/drivingStop, travelExpense/mileageAllowance, travelExpense/passenger, travelExpense/paymentType, travelExpense/perDiemCompensation, travelExpense/rate, travelExpense/rateCategory, travelExpense/rateCategoryGroup, travelExpense/settings, travelExpense/zone, userLicense, vatReturns/comment, vatTermSizeSettings, voucherApprovalListElement, voucherInbox, voucherMessage, voucherStatus, yearEnd, yearEnd/enumType