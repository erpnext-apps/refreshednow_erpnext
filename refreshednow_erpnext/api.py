import frappe
from frappe import _
import json
import calendar
#from datetime import date, datetime, timedelta
from frappe.desk.reportview import get_match_cond
import json, pdfkit, os
from frappe.utils.pdf import get_pdf

import datetime
from dateutil import tz

# @frappe.whitelist()
# def rn_events_test(start, end, filters=None):
# 	events = [
# 		{ "id": '1', "start": '2016-12-20', "end": '2016-12-20', "title": 'event 1'},
# 		{ "id": '2', "start": '2016-12-20T09:00:00', "end": '2016-12-20T14:00:00', "title": 'event 2'},
# 		{ "id": '3', "start": '2016-12-21T11:30:00', "end": '2016-12-21T12:00:00', "title": 'event 3' },
# 		{ "id": '4', "start": '2016-12-22T07:30:00', "end": '2016-12-22T09:30:00', "title": 'event 4' },
# 		{ "id": '5', "start": '2016-12-23T10:00:00', "end": '2016-12-23T15:00:00', "title": 'event 5' },
# 		{ "id": '6', "start": '2016-12-24T10:00:00', "end": '2016-12-24T15:00:00', "title": filters }
# 	]
# 	return events

@frappe.whitelist()
def rn_events(start=None, end=None, filters=None):
	slots = []

	if filters:
		filters = json.loads(filters)
		service_item = frappe.get_doc("Item", filters["service_type"])
		service_date = frappe.utils.data.get_datetime(filters["scheduled_date"]) or frappe.utils.datetime.datetime.today()

		date_range = get_date_range(service_date)

		days = (date_range[1] - date_range[0]).days

		iter_date = date_range[0]

		for x in xrange(0, days):
			start_time = iter_date
			start_time = start_time.replace(hour=int(service_item.rn_start_time_hours), minute=int(service_item.rn_start_time_minutes), second=0, microsecond=0)

			end_time = iter_date
			end_time = end_time.replace(hour=int(service_item.rn_end_time_hours), minute=int(service_item.rn_end_time_minutes), second=0, microsecond=0)

			daily_slots = get_slots_with_break(hours=[start_time, end_time],
				duration=frappe.utils.datetime.timedelta(minutes=int(service_item.rn_service_duration)),
				break_time=service_item.rn_break_start_time_hours + ":" + service_item.rn_break_start_time_minutes + ":00",
				break_duration=frappe.utils.datetime.timedelta(minutes=int(service_item.rn_break_duration)))

			for slot in daily_slots:
				daily_available_slots = get_available_teams_for_slot(service_item, slot["start"])

				if daily_available_slots == 0:
					event_title = "-"
					slot_color = "#ff5c5c"
				elif slot.get("type") == "break":
					event_title = "Break"
					slot_color = "grey"
				else:
					event_title = daily_available_slots
					slot_color = "#5cbbff"

				slot.update( {"id": frappe.generate_hash(length=5), "title": event_title, "className": "rn-team", "color": slot_color })

			slots = slots + daily_slots

			#print iter_date

			iter_date = iter_date + frappe.utils.datetime.timedelta(days=1)

	return slots


def get_slots_with_break(hours,duration=frappe.utils.datetime.timedelta(hours=1), break_time="12:00:00", break_duration=frappe.utils.datetime.timedelta(minutes=30)):
	break_start = frappe.utils.datetime.datetime.combine(hours[0].date(), frappe.utils.get_time(break_time))

	pre_break_slots = get_slots([hours[0], break_start - duration], duration)
	break_slot = [frappe._dict({"start":break_start.isoformat(), "end":(break_start + break_duration).isoformat(), "type":"break"})]
	post_break_slots = get_slots([break_start + break_duration, hours[1]], duration)

	return pre_break_slots + break_slot + post_break_slots

def get_slots(hours, duration=frappe.utils.datetime.timedelta(hours=1)): #, break_time="12:00:00", break_duration=frappe.utils.datetime.timedelta(minutes=30)):
	"""
	Generate Timeslots based on list of hours and duration

	:param hours: list of hours = [frappe.utils.datetime.datetime(2016, 12, 14, 9),
																frappe.utils.datetime.datetime(2016, 12, 14, 18)]
	:param duration: default duration of one hour.
	"""
	out = []
	# break_start = frappe.utils.datetime.datetime.combine(hours[0].date(), frappe.utils.get_time(break_time))

	# print "Break start", break_start

	actual_slot_count = 0

	slots = sorted([(hours[0], hours[0])] + [(hours[1], hours[1])])
	for start, end in ((slots[i][1], slots[i+1][0]) for i in range(len(slots)-1)):
			assert start <= end, "Start time should be before end time"

			while True:
				slot = frappe._dict({"start":start.isoformat(), "end":(start +  duration).isoformat()})

				actual_slot_count += 1

				out.append(slot)
				start +=  duration

				if start > end:
					break

	return out

@frappe.whitelist()
def get_settings(fieldname):
	try:
		out = frappe.db.get_value("RN Settings", "RN Settings", fieldname)
	except Exception as e:
		out = ""

	return out

#TODO: Refactor. Use nested dict instead of list of dict {"item_code": "RefGO", "data" : {"start_time" ...}}
@frappe.whitelist()
def get_service_item_data():
	service_items = frappe.get_all("Item",
		filters={"item_group": get_settings("rn_service_item_group")},
		fields=["name", "item_code",
				"rn_start_time_hours", "rn_start_time_minutes", "rn_end_time_hours", "rn_end_time_minutes", "rn_service_duration",
				"rn_break_duration", "rn_break_start_time_hours", "rn_break_start_time_minutes"])

	out = []
	for item in service_items:
		out.append(
			frappe._dict({
				"item_code": item.get("item_code"),
				"start_time": "{0}:{1}:00".format(item.get("rn_start_time_hours"), item.get("rn_start_time_minutes")),
				"end_time": "{0}:{1}:00".format(item.get("rn_end_time_hours"), item.get("rn_end_time_minutes")),
				"teams": frappe.get_all("RN Team", filters={"service_type": item.get("item_code")}),
				"service_duration": item.get("rn_service_duration")
			})
		)

	return out

@frappe.whitelist()
def get_rn_daily_resources(filters):
	filters = json.loads(filters)

	out_teams = []
	teams_by_service = frappe.get_all("RN Team", filters={ "service_type": filters["service_type"] }, fields=['name'], order_by="name")

	scheduled_date_time = frappe.utils.get_datetime(filters["scheduled_date"] + ' ' + filters["scheduled_time"])
	scheduled_dow = scheduled_date_time.strftime("%A")

	for team in teams_by_service:
		if len(frappe.get_all("RN Team Day Employee", {"team": team.name, "day_of_week": scheduled_dow})) > 0:
			out_teams.append({"id":team.name, "title":team.name})

	return out_teams

@frappe.whitelist()
def get_rn_daily_events(start, end, filters=None):
	filters = json.loads(filters)

	out_services = []

	scheduled_services = frappe.get_all("RN Scheduled Service", \
		filters=[["service_type", "=", filters["service_type"]], \
		["starts_on", "=", frappe.utils.data.get_datetime(filters["scheduled_date"] + ' ' + filters["scheduled_time"])],
		["docstatus", "!=", 2]], fields=['*'])

	for service in scheduled_services:
		print ("Service: ", service.name)

		service_color = "grey"
		if service.get("workflow_state") == "To Schedule":
			service_color = "#5cbbff"

		if service.get("workflow_state") == "To Dispatch":
			service_color = "#ffd55c"

		if service.get("workflow_state") == "To Bill":
			service_color = "#ff985c"

		if service.get("workflow_state") == "Completed":
			service_color = "#c0ff5c"

		if service.get("workflow_state") == "Stopped":
			service_color = "grey"

		out_services.append({"id": service.name,
			"resourceId": service.team,
			"start": service.starts_on.isoformat(),
			"end": service.ends_on.isoformat(),
			"className": "rn-team",
			"color": service_color })

	return out_services

#Datasource for weekly grid. Available people
@frappe.whitelist()
def get_available_teams_for_slot(service_item, start_time):
	#Get list of scheduled services for week.
	#scheduled_services_for_date = frappe.get_all("RN Scheduled Service", filters={"service_type": service_type, "scheduled_date": ref_date})

	#Get teams by service.
	teams_for_service = frappe.get_all("RN Team", filters={"service_type" : service_item.name })

	no_of_teams_for_service = 0

	for team in teams_for_service:
		allocations = frappe.get_all("RN Team Day Employee", filters={"team":team.name, "day_of_week": frappe.utils.get_datetime(start_time).strftime("%A") })
		if len(allocations) > 0:
			no_of_teams_for_service += 1

	no_of_booked_services = len(frappe.get_all("RN Scheduled Service", \
		filters=[["service_type", "=", service_item.name], \
		["starts_on","=",start_time],
		["docstatus", "!=", 2]]))

	available_teams_for_slot = (no_of_teams_for_service - no_of_booked_services) or 0

	return available_teams_for_slot


def get_service_wise_total_count_of_teams():
	out = []

	service_items = frappe.get_all("Item",
		filters={"item_group": get_settings("rn_service_item_group")},
		fields=["name", "item_code"])

	for item in service_items:
		no_of_teams = int(frappe.db.count("RN Team", filters={"service_type": item.name})) or 0
		out.append(frappe._dict({ "service_type": item.name, "teams": no_of_teams }))

	return out

def get_week_range(date):
	"""Find the first/last day of the week for the given day.
	Assuming weeks start on Sunday and end on Saturday.

	Returns a tuple of ``(start_date, end_date)``.

	"""
	# isocalendar calculates the year, week of the year, and day of the week.
	# dow is Mon = 1, Sat = 6, Sun = 7
	year, week, dow = date.isocalendar()

	# Find the first day of the week.
	if dow == 7:
		# Since we want to start with Sunday, let's test for that condition.
		start_date = date
	else:
		# Otherwise, subtract `dow` number days to get the first day
		start_date = date - frappe.utils.datetime.timedelta(dow)

	# Now, add 6 for the last day of the week (i.e., count up to Saturday)
	end_date = start_date + frappe.utils.datetime.timedelta(7)

	return [start_date, end_date]

def get_month_range(scheduled_date):
	year = scheduled_date.year
	month = scheduled_date.month

	num_days = calendar.monthrange(year, month)[1]
	days = [frappe.utils.datetime.datetime(year, month, day) for day in range(1, num_days+1)]

	out = [min(days),max(days)]
	return out

def get_date_range(scheduled_date, days_delta=7):
	return [scheduled_date - frappe.utils.datetime.timedelta(days=days_delta), scheduled_date + frappe.utils.datetime.timedelta(days=days_delta)]

@frappe.whitelist()
def customer_vehicle_onload(self,method):
	self.get("__onload").customer_vehicle = frappe.get_all("Vehicle", fields=['*'],filters =[["rn_customer", "=", self.name]])

@frappe.whitelist()
def get_team_members(team_name, day_of_week):
	members = frappe.db.get_all("RN Team Day Employee", filters={"team":team_name, "day_of_week": day_of_week}, fields=['*'])
	for member in members:
		member.update({"member_name": frappe.db.get_value("Employee", member.employee, "employee_name")})

	return members

def vehicle_validate(self, method):
	self.rn_model_make = self.make + ' ' + self.model

def sales_order_on_submit(self, method):
	pass

def sales_order_on_cancel(self, method):
	pass

def pe_on_submit(self, method):
	invoices = [inv.reference_name for inv in self.references if inv.reference_doctype == "Sales Invoice"]

	for i in invoices:
		rnss_id = frappe.db.get_value("Sales Invoice", i, "rn_scheduled_service")

		if rnss_id:
			frappe.db.set_value("RN Scheduled Service", rnss_id, "workflow_state", "Completed")
			frappe.db.commit()

def pe_on_cancel(self, method):
	invoices = [inv.reference_name for inv in self.references if inv.reference_doctype == "Sales Invoice"]

	for i in invoices:
		rnss_id = frappe.db.get_value("Sales Invoice", i, "rn_scheduled_service")

		if rnss_id:
			frappe.db.set_value("RN Scheduled Service", rnss_id, "workflow_state", "To Bill")
			frappe.db.commit()

#Team Tool
@frappe.whitelist()
def get_team_tool_data(service_type=None, day_of_week=None):
	out = {"data": None}

	if service_type and day_of_week:
		teams =  frappe.get_all("RN Team", filters={"service_type":service_type})

		designations = frappe.get_all("RN Team Staff Detail", fields=["designation"], distinct=True)
		designations = [d.designation for d in designations]

		employees = frappe.get_all("Employee", filters=[["designation", "in", designations]], fields=["name", "employee_name", "designation", "rn_weekly_off"]) #TODO: Filter for On-Field employees.
		team_names = [t.name for t in teams]
		allocations = frappe.get_all("RN Team Day Employee", filters=[["team", "in", team_names], ["day_of_week", "=", day_of_week]], fields=["*"])

		out = {"data": { "teams": teams, "employees" : employees, "allocations": allocations, "day_of_week": day_of_week } }

	return out

@frappe.whitelist()
def update_team_day_employee(employee, team, day_of_week):
	allocations = frappe.get_all("RN Team Day Employee", filters={"employee": employee, "day_of_week": day_of_week}, fields=["*"])

	weekly_off = frappe.db.get_value("Employee", employee, "rn_weekly_off")
	if weekly_off == day_of_week:
		return {"exc": "Cannot schedule on this day. Weekly off."}

	if len(allocations) == 1:
		allocation = frappe.get_doc("RN Team Day Employee", allocations[0].get("name"))
	else:
		allocation = frappe.new_doc("RN Team Day Employee")

	allocation.employee = employee
	allocation.team = team
	allocation.day_of_week = day_of_week
	allocation.save()

	frappe.db.commit()

@frappe.whitelist()
def cancel_all_allocations(employee, day_of_week):
	allocations = frappe.get_all("RN Team Day Employee", filters={"employee": employee, "day_of_week": day_of_week}, fields=["*"])

	for a in allocations:
		frappe.delete_doc("RN Team Day Employee", a.name)

	frappe.db.commit()

def item_validate(self, method):
	if (self.rn_break_duration % 15 != 0):
		frappe.throw("Break duration must be in intervals of 15 minutes.")

	if (self.rn_service_duration % 15 != 0):
		frappe.throw("Service duration must be in intervals of 15 minutes.")

@frappe.whitelist()
def get_availability_for_team_dow(team, day_of_week):
	allocations = frappe.get_all("RN Team Day Employee", filters={"team":team, "day_of_week":day_of_week})
	if len(allocations) == 0:
		return {"exc": "No available team members for this slot."}

# searches for customer
@frappe.whitelist()
def customer_query(doctype, txt, searchfield, start, page_len, filters):
	# return frappe.db.sql(""" select `tabContact`.name from `tabContact`, `tabDynamic Link`
	# 	where `tabDynamic Link`.link_doctype = 'Supplier' and (`tabDynamic Link`.link_name = %(name)s
	# 	or `tabDynamic Link`.link_name like %(txt)s) and `tabContact`.name = `tabDynamic Link`.parent
	# 	limit %(start)s, %(page_len)s""", {"start": start, "page_len":page_len, "txt": "%%%s%%" % txt, "name": filters.get('supplier')})


	return frappe.db.sql("""select C.name, D.contact_number from `tabCustomer` AS C left outer join (select A.parent, A.link_name, IFNULL(B.mobile_no, B.phone) AS contact_number from `tabDynamic Link` AS A inner join `tabContact` AS B on A.parent=B.name where A.parenttype = "contact") AS D on C.name = D.link_name

		where
			({key} like %(txt)s
				or C.name like %(txt)s
				or D.contact_number like %(txt)s)
				and disabled=0
		order by
			if(locate(%(_txt)s, C.name), locate(%(_txt)s, C.name), 99999),
			idx desc,
			C.name
		limit %(start)s, %(page_len)s""".format(**{
			"key": searchfield
		}), {
			'txt': "%%%s%%" % txt,
			'_txt': txt.replace("%", ""),
			'start': start,
			'page_len': page_len
		})


# select A.parent, A.link_name, B.customer from `tabDynamic Link` AS A inner join `tabAddress` AS B on A.link_name=B.customer where B.address_type="Service";



@frappe.whitelist()
def contact_query(doctype, txt, searchfield, start, page_len, filters):
	out = frappe.db.sql("""select A.parent, A.link_name, B.mobile_no, B.phone
		from `tabDynamic Link` AS A inner join `tabContact` AS B on A.parent=B.name
		where
			A.parenttype="contact" and
			A.link_name = '{customer}'and
			({key} like %(txt)s
				or A.parent like %(txt)s
				or mobile_no like %(txt)s
				or phone like %(txt)s)
		order by
			if(locate(%(_txt)s, B.name), locate(%(_txt)s, B.name), 99999),
			B.idx desc,
			B.name
		limit %(start)s, %(page_len)s""".format(**{
			"key":"B.name" if  searchfield == "name" else searchfield,
			'customer': filters.get('customer')
		}), {
			'txt': "%%%s%%" % txt,
			'_txt': txt.replace("%", ""),
			'start': start,
			'page_len': page_len

		})
	for x in xrange(1,10):
		print (out)
	return out


@frappe.whitelist()
def get_address(doctype, txt, searchfield, start, page_len, filters):
	out = frappe.db.sql("""select A.parent, A.link_name, B.address_line1, B.address_line2, B.city, B.country
		from `tabDynamic Link` AS A inner join `tabAddress` AS B on A.parent = B.name
		where
			A.parenttype="address" and
			A.link_name = '{customer}'and
			B.address_type = '{address_type}' and
			({key} like %(txt)s
			or A.parent like %(txt)s
			or B.address_line1 like %(txt)s
			or B.address_line2 like %(txt)s
			or B.city like %(txt)s
			or B.country like %(txt)s)
		order by
			if(locate(%(_txt)s, B.name), locate(%(_txt)s, B.name), 99999),
			B.idx desc,
			B.name
		limit %(start)s, %(page_len)s""".format(**{
			"key":"B.name" if  searchfield == "name" else searchfield,
			'customer': filters.get('customer'),
			'address_type': filters.get('address_type'),
		}), {
			'txt': "%%%s%%" % txt,
			'_txt': txt.replace("%", ""),
			'start': start,
			'page_len': page_len

		})
	for x in xrange(1,10):
		print (out)
	return out




# def get_customer_links(customer):
# 	pass

@frappe.whitelist()
def get_customer_info(customer):
	#return {"address": "ABC"}
	contacts = frappe.get_all("Dynamic Link", filters={"parenttype": "Contact", "link_name": customer}, fields=["*"], order_by="creation DESC")
	addresses = frappe.get_all("Dynamic Link", filters={"parenttype": "Address", "link_name": customer}, fields=["*"], order_by="creation DESC")

	contact = ""
	if len(contacts) > 0:
		contact = contacts[0].parent

	address = ""
	if len(addresses) > 0:
		address = addresses[0].parent

	return {"address": address, "contact": contact }


@frappe.whitelist()
def print_job_sheet(names):
	if not frappe.has_permission("RN Scheduled Service", "write"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if len(names) == 0:
		frappe.msgprint("No rows selected.")

	final_html = prepare_bulk_print_html(names)

	pdf_options = {
					"no-outline": None,
					"encoding": "UTF-8",
					"title": "Job Sheet"
				}

	frappe.local.response.filename = "{filename}.pdf".format(filename="job_sheet_list".replace(" ", "-").replace("/", "-"))
	frappe.local.response.filecontent = rn_get_pdf(final_html, options=pdf_options)
	frappe.local.response.type = "download"


def prepare_bulk_print_html(names):
	names = names.split(",")
	html = ""
	ss_list = []

	for name in names:
		ss = frappe.get_doc("RN Scheduled Service", name)
		employee = frappe.db.get_value("RN Team Day Employee", {"team":ss.team,"day_of_week":calendar.day_name[ss.starts_on.weekday()]},"employee")
		cleaner_name = frappe.db.get_value("Employee", employee, "employee_name")
		ss.update({"cleaner":cleaner_name})
		ss_list.append(ss)

	ss_list = sorted(ss_list, key=lambda v:v.get("starts_on"))

	html_params = { "ss_list": ss_list }
	final_html = frappe.render_template("refreshednow_erpnext/templates/includes/refreshed_jobsheet.html", html_params)

	return final_html


def rn_get_pdf(html, options=None):
	fname = os.path.join("/tmp", "refreshed-jobsheet-{0}.pdf".format(frappe.generate_hash()))

	try:
		pdfkit.from_string(html, fname, options=options or {})

		with open(fname, "rb") as fileobj:
			filedata = fileobj.read()

	except IOError as e:
		if ("ContentNotFoundError" in e.message
			or "ContentOperationNotPermittedError" in e.message
			or "UnknownContentError" in e.message
			or "RemoteHostClosedError" in e.message):

			# allow pdfs with missing images if file got created
			if os.path.exists(fname):
				with open(fname, "rb") as fileobj:
					filedata = fileobj.read()

			else:
				frappe.throw(_("PDF generation failed because of broken image links"))
		else:
			raise

	finally:
		cleanup(fname)

	return filedata

def cleanup(fname):
	if os.path.exists(fname):
		os.remove(fname)

@frappe.whitelist()
def send_sms(mobile_no, message):
	import requests

	sms_settings = frappe.get_doc("SMS Settings")

	querystring = {}

	for p in sms_settings.parameters:
		querystring.update({p.parameter:p.value})

	querystring.update({
		"sendername":sms_settings.sms_sender_name,
		sms_settings.receiver_parameter:mobile_no,
		sms_settings.message_parameter:message
	})

	#print sms_settings.sms_gateway_url, querystring
	response = requests.request("GET", sms_settings.sms_gateway_url, params=querystring)
	return response.text

def hourly_call():
	ex = None
	try:
		send_service_reminder_sms()
	except Exception as e:
		ex = e
		note = frappe.new_doc("Note")
		note.title = "Hourly beat {0}".format(frappe.utils.nowdate() + frappe.utils.nowtime())
		note.public = 1
		note.content = "Hourly beat. <hr> {0}".format(ex) if ex else "No exception"
		note.save()
		frappe.db.commit()


def send_service_reminder_sms():

	def get_msg(service, on_day):
		sms_message = """We look forward to refreshing your car {on_day}, {on_time} using {service_type}.
		 Thanks for using Refreshed Car Care.""".format(
			on_day=on_day,
			on_time=frappe.utils.data.format_datetime(service.starts_on,"EEEE MMM d") + " at " + frappe.utils.data.format_datetime(service.starts_on, "h:mm a").lower(),
			service_type=service.service_type
		)
		return sms_message



	nowtime_utc = frappe.utils.datetime.datetime.utcnow()
	nowtime_utc = nowtime_utc.replace(tzinfo=tz.gettz("UTC"))
	nowtime_ak = nowtime_utc.astimezone(tz.gettz("Asia/Kolkata"))

	#Comparison times are adjusted for SF time.

	if nowtime_ak.hour in [20,21,22]:
		tomorrow = frappe.utils.data.add_to_date(frappe.utils.today(), days=1)
		services = frappe.db.sql("""SELECT * FROM `tabRN Scheduled Service`
						WHERE date(starts_on) = '{starts_on_date}'
						AND docstatus = 1
						AND sms_checkbox != 1""".format(
							starts_on_date=tomorrow
						), as_dict=1)

		for service in services:
			msg = get_msg(service, "tomorrow")

			note_content = ""
			try:
				send_sms(service.contact_phone, msg)
				note_content = "Sent message to {0} on {1} <hr> {2} <hr> {3}".format(service.customer or "'No Cust'", service.contact_phone or "'Phone No'",  msg or "'Message'", service.name or "'Service Name'")
				frappe.db.set_value("RN Scheduled Service", service.name, "sms_checkbox", 1)
				frappe.db.commit()
			except Exception as e:
				note_content = "Unable to send message to {0} on {1} <hr> {2} <hr> {3} <hr> {4}".format(service.customer or "'No Cust'", service.contact_phone or "'Phone No'",  msg or "'Message'", service.name or "'Service Name'", ex)


			note = frappe.new_doc("Note")
			note.title = "SMS Log (Reminder) - "+ frappe.utils.nowdate() + frappe.utils.nowtime()
			note.public = 1
			note.content = note_content
			note.save()

			frappe.db.commit()
