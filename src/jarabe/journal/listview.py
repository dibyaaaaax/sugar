# Copyright (C) 2007, One Laptop Per Child
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

import logging
import traceback
import sys
from gettext import gettext as _
import time

import hippo
import gobject
import gtk
import dbus

from sugar.graphics import style
from sugar.graphics.icon import CanvasIcon, Icon

from jarabe.journal.collapsedentry import CollapsedEntry
from jarabe.journal import model

DS_DBUS_SERVICE = 'org.laptop.sugar.DataStore'
DS_DBUS_INTERFACE = 'org.laptop.sugar.DataStore'
DS_DBUS_PATH = '/org/laptop/sugar/DataStore'

UPDATE_INTERVAL = 300

EMPTY_JOURNAL = _("Your Journal is empty")
NO_MATCH = _("No matching entries ")

class BaseListView(gtk.HBox):
    __gtype_name__ = 'BaseListView'

    __gsignals__ = {
        'clear-clicked': (gobject.SIGNAL_RUN_FIRST,
                          gobject.TYPE_NONE,
                          ([]))
    }

    def __init__(self):
        self._query = {}
        self._result_set = None
        self._entries = []
        self._page_size = 0
        self._reflow_sid = 0
        self._do_scroll_hid = None
        self._progress_bar = None
        self._last_progress_bar_pulse = None

        gtk.HBox.__init__(self)
        self.set_flags(gtk.HAS_FOCUS|gtk.CAN_FOCUS)
        self.connect('key-press-event', self._key_press_event_cb)

        self._box = hippo.CanvasBox(
                        orientation=hippo.ORIENTATION_VERTICAL,
                        background_color=style.COLOR_WHITE.get_int())

        self._canvas = hippo.Canvas()
        self._canvas.set_root(self._box)

        self.pack_start(self._canvas)
        self._canvas.show()

        self._vadjustment = gtk.Adjustment(value=0, lower=0, upper=0, 
                                           step_incr=1, page_incr=0,
                                           page_size=0)
        self._vadjustment.connect('value-changed',
                                  self._vadjustment_value_changed_cb)
        self._vadjustment.connect('changed', self._vadjustment_changed_cb)

        self._vscrollbar = gtk.VScrollbar(self._vadjustment)
        self.pack_end(self._vscrollbar, expand=False, fill=False)
        self._vscrollbar.show()
        
        self.connect('scroll-event', self._scroll_event_cb)
        self.connect('destroy', self.__destroy_cb)

        # DND stuff
        self._temp_file_path = None
        self._pressed_button = None
        self._press_start_x = None
        self._press_start_y = None
        self._last_clicked_entry = None
        self._canvas.drag_source_set(0, [], 0)
        self._canvas.add_events(gtk.gdk.BUTTON_PRESS_MASK |
                          gtk.gdk.POINTER_MOTION_HINT_MASK)
        self._canvas.connect_after("motion_notify_event",
                       self._canvas_motion_notify_event_cb)
        self._canvas.connect("button_press_event",
                       self._canvas_button_press_event_cb)
        self._canvas.connect("drag_end", self._drag_end_cb)
        self._canvas.connect("drag_data_get", self._drag_data_get_cb)

        # Auto-update stuff
        self._fully_obscured = True
        self._dirty = False
        self._refresh_idle_handler = None
        self._update_dates_timer = None

        bus = dbus.SessionBus()
        datastore = dbus.Interface(
            bus.get_object(DS_DBUS_SERVICE, DS_DBUS_PATH), DS_DBUS_INTERFACE)
        self._datastore_created_handler = \
                datastore.connect_to_signal('Created',
                                             self.__datastore_created_cb)
        self._datastore_updated_handler = \
                datastore.connect_to_signal('Updated',
                                            self.__datastore_updated_cb)

        self._datastore_deleted_handler = \
                datastore.connect_to_signal('Deleted',
                                            self.__datastore_deleted_cb)

    def __destroy_cb(self, widget):
        self._datastore_created_handler.remove()
        self._datastore_updated_handler.remove()
        self._datastore_deleted_handler.remove()

    def _vadjustment_changed_cb(self, vadjustment):
        if vadjustment.props.upper > self._page_size:
            self._vscrollbar.show()
        else:
            self._vscrollbar.hide()

    def _vadjustment_value_changed_cb(self, vadjustment):
        if self._do_scroll_hid is None:
            self._do_scroll_hid = gobject.idle_add(self._do_scroll)

    def _do_scroll(self):
        current_position = int(self._vadjustment.props.value)

        self._result_set.seek(current_position)
        metadata_list = self._result_set.read(self._page_size)

        if self._result_set.length != self._vadjustment.props.upper:
            self._vadjustment.props.upper = self._result_set.length
            self._vadjustment.changed()

        self._refresh_view(metadata_list)
        self._dirty = False

        self._do_scroll_hid = None                
        return False

    def _refresh_view(self, metadata_list):
        logging.debug('ListView %r' % self)
        # Indicate when the Journal is empty
        if len(metadata_list) == 0:
            if self._is_query_empty():
                self._show_message(EMPTY_JOURNAL)
            else:
                self._show_message(NO_MATCH)
            return

        # Refresh view and create the entries if they don't exist yet.
        for i in range(0, self._page_size):
            try:
                if i < len(metadata_list):
                    if i >= len(self._entries):
                        entry = self.create_entry()
                        self._box.append(entry)
                        self._entries.append(entry)
                        entry.metadata = metadata_list[i]
                    else:
                        entry = self._entries[i]
                        entry.metadata = metadata_list[i]
                        entry.set_visible(True)
                elif i < len(self._entries):
                    entry = self._entries[i]
                    entry.set_visible(False)
            except Exception:
                logging.error('Exception while displaying entry:\n' + \
                    ''.join(traceback.format_exception(*sys.exc_info())))

    def create_entry(self):
        """ Create a descendant of BaseCollapsedEntry
        """
        raise NotImplementedError

    def update_with_query(self, query_dict):
        logging.debug('ListView.update_with_query')
        self._query = query_dict
        if self._page_size > 0:
            self.refresh()

    def refresh(self):
        logging.debug('ListView.refresh query %r' % self._query)
        self._stop_progress_bar()
        self._start_progress_bar()
        if self._result_set is not None:
            self._result_set.stop()

        self._result_set = model.find(self._query)
        self._result_set.ready.connect(self.__result_set_ready_cb)
        self._result_set.progress.connect(self.__result_set_progress_cb)
        self._result_set.setup()

    def __result_set_ready_cb(self, **kwargs):
        if kwargs['sender'] != self._result_set:
            return

        self._stop_progress_bar()

        self._vadjustment.props.upper = self._result_set.length
        self._vadjustment.changed()

        self._vadjustment.props.value = min(self._vadjustment.props.value,
                self._result_set.length - self._page_size)
        if self._result_set.length == 0:
            if self._is_query_empty():
                self._show_message(EMPTY_JOURNAL)
            else:
                self._show_message(NO_MATCH)
        else:
            self._clear_message()
            self._do_scroll()

    def _is_query_empty(self):
        # FIXME: This is a hack, we shouldn't have to update this every time
        # a new search term is added.
        if self._query.get('query', '') or self._query.get('mime_type', '') or \
                self._query.get('keep', '') or self._query.get('mtime', '') or \
                self._query.get('activity', ''):
            return False
        else:
            return True

    def __result_set_progress_cb(self, **kwargs):
        if time.time() - self._last_progress_bar_pulse > 0.05:
            if self._progress_bar is not None:
                self._progress_bar.pulse()
                self._last_progress_bar_pulse = time.time()

    def _start_progress_bar(self):
        self.remove(self._canvas)
        self.remove(self._vscrollbar)

        alignment = gtk.Alignment(xalign=0.5, yalign=0.5, xscale=0.5)
        self.pack_start(alignment)
        alignment.show()

        self._progress_bar = gtk.ProgressBar()
        self._progress_bar.props.pulse_step = 0.01
        self._last_progress_bar_pulse = time.time()
        alignment.add(self._progress_bar)
        self._progress_bar.show()

    def _stop_progress_bar(self):
        for widget in self.get_children():
            self.remove(widget)
        self._progress_bar = None

        self.pack_start(self._canvas)
        self.pack_end(self._vscrollbar, expand=False, fill=False)

    def _scroll_event_cb(self, hbox, event):
        if event.direction == gtk.gdk.SCROLL_UP:
            if self._vadjustment.props.value > self._vadjustment.props.lower:
                self._vadjustment.props.value -= 1
        elif event.direction == gtk.gdk.SCROLL_DOWN:
            max_value = self._result_set.length - self._page_size
            if self._vadjustment.props.value < max_value:
                self._vadjustment.props.value += 1

    def do_focus(self, direction):
        if not self.is_focus():
            self.grab_focus()
            return True
        return False

    def _key_press_event_cb(self, widget, event):
        keyname = gtk.gdk.keyval_name(event.keyval)

        if keyname == 'Up':
            if self._vadjustment.props.value > self._vadjustment.props.lower:
                self._vadjustment.props.value -= 1
        elif keyname == 'Down':
            max_value = self._result_set.length - self._page_size
            if self._vadjustment.props.value < max_value:
                self._vadjustment.props.value += 1
        elif keyname == 'Page_Up' or keyname == 'KP_Page_Up':
            new_position = max(0, 
                               self._vadjustment.props.value - self._page_size)
            if new_position != self._vadjustment.props.value:
                self._vadjustment.props.value = new_position
        elif keyname == 'Page_Down' or keyname == 'KP_Page_Down':
            new_position = min(self._result_set.length - self._page_size,
                               self._vadjustment.props.value + self._page_size)
            if new_position != self._vadjustment.props.value:
                self._vadjustment.props.value = new_position
        elif keyname == 'Home' or keyname == 'KP_Home':
            new_position = 0
            if new_position != self._vadjustment.props.value:
                self._vadjustment.props.value = new_position
        elif keyname == 'End' or keyname == 'KP_End':
            new_position = max(0, self._result_set.length - self._page_size)
            if new_position != self._vadjustment.props.value:
                self._vadjustment.props.value = new_position
        else:
            return False

        return True

    def do_size_allocate(self, allocation):
        gtk.HBox.do_size_allocate(self, allocation)
        new_page_size = int(allocation.height / style.GRID_CELL_SIZE)

        logging.debug("do_size_allocate: %r" % new_page_size)
        
        if new_page_size != self._page_size:
            self._page_size = new_page_size
            self._queue_reflow()

    def _queue_reflow(self):
        if not self._reflow_sid:
            self._reflow_sid = gobject.idle_add(self._reflow_idle_cb)

    def _reflow_idle_cb(self):
        self._box.clear()
        self._entries = []

        self._vadjustment.props.page_size = self._page_size
        self._vadjustment.props.page_increment = self._page_size
        self._vadjustment.changed()

        if self._result_set is None:
            self._result_set = model.find(self._query)

        max_value = max(0, self._result_set.length - self._page_size)
        if self._vadjustment.props.value > max_value:
            self._vadjustment.props.value = max_value
        else:
            self._do_scroll()

        self._reflow_sid = 0

    def _show_message(self, message):
        box = hippo.CanvasBox(orientation=hippo.ORIENTATION_VERTICAL,
                              background_color=style.COLOR_WHITE.get_int(),
                              yalign=hippo.ALIGNMENT_CENTER,
                              spacing=style.DEFAULT_SPACING,
                              padding_bottom=style.GRID_CELL_SIZE)
        self._canvas.set_root(box)

        icon = CanvasIcon(size=style.LARGE_ICON_SIZE,
                          icon_name='activity-journal',
                          stroke_color = style.COLOR_BUTTON_GREY.get_svg(),
                          fill_color = style.COLOR_TRANSPARENT.get_svg())
        box.append(icon)

        text = hippo.CanvasText(text=message,
                xalign=hippo.ALIGNMENT_CENTER,
                font_desc=style.FONT_BOLD.get_pango_desc(),
                color = style.COLOR_BUTTON_GREY.get_int())
        box.append(text)

        button = gtk.Button(label=_('Clear search'))
        button.connect('clicked', self.__clear_button_clicked_cb)
        button.props.image = Icon(icon_name='dialog-cancel',
                                  icon_size=gtk.ICON_SIZE_BUTTON)
        canvas_button = hippo.CanvasWidget(widget=button,
                                           xalign=hippo.ALIGNMENT_CENTER)
        box.append(canvas_button)

    def __clear_button_clicked_cb(self, button):
        self.emit('clear-clicked')

    def _clear_message(self):
        self._canvas.set_root(self._box)

    # TODO: Dnd methods. This should be merged somehow inside hippo-canvas.
    def _canvas_motion_notify_event_cb(self, widget, event):
        if not self._pressed_button:
            return True
        
        # if the mouse button is not pressed, no drag should occurr
        if not event.state & gtk.gdk.BUTTON1_MASK:
            self._pressed_button = None
            return True

        logging.debug("motion_notify_event_cb")
                        
        if event.is_hint:
            x, y, state_ = event.window.get_pointer()
        else:
            x = event.x
            y = event.y

        if widget.drag_check_threshold(int(self._press_start_x),
                                       int(self._press_start_y),
                                       int(x),
                                       int(y)):
            context_ = widget.drag_begin([('text/uri-list', 0, 0),
                                          ('journal-object-id', 0, 0)],
                                         gtk.gdk.ACTION_COPY,
                                         1,
                                         event)
        return True

    def _drag_end_cb(self, widget, drag_context):
        logging.debug("drag_end_cb")
        self._pressed_button = None
        self._press_start_x = None
        self._press_start_y = None
        self._last_clicked_entry = None

        # Release and delete the temp file
        self._temp_file_path = None

    def _drag_data_get_cb(self, widget, context, selection, target_type,
                          event_time):
        logging.debug("drag_data_get_cb: requested target " + selection.target)

        metadata = self._last_clicked_entry.metadata
        if selection.target == 'text/uri-list':
            # Get hold of a reference so the temp file doesn't get deleted
            self._temp_file_path = model.get_file(metadata['uid'])
            selection.set(selection.target, 8, self._temp_file_path)
        elif selection.target == 'journal-object-id':
            selection.set(selection.target, 8, metadata['uid'])

    def _canvas_button_press_event_cb(self, widget, event):
        logging.debug("button_press_event_cb")

        if event.button == 1 and event.type == gtk.gdk.BUTTON_PRESS:
            self._last_clicked_entry = \
                    self._get_entry_at_coords(event.x, event.y)
            if self._last_clicked_entry:
                self._pressed_button = event.button
                self._press_start_x = event.x
                self._press_start_y = event.y

        return False

    def _get_entry_at_coords(self, x, y):
        for entry in self._box.get_children():
            entry_x, entry_y = entry.get_context().translate_to_widget(entry)
            entry_width, entry_height = entry.get_allocation()

            if (x >= entry_x ) and (x <= entry_x + entry_width) and        \
                    (y >= entry_y ) and (y <= entry_y + entry_height):
                return entry
        return None

    def update_dates(self):
        logging.debug('ListView.update_dates')
        for entry in self._entries:
            if entry.get_visible():
                entry.update_date()

    def __datastore_created_cb(self, uid):
        self._set_dirty()
        
    def __datastore_updated_cb(self, uid):
        self._set_dirty()
        
    def __datastore_deleted_cb(self, uid):
        self._set_dirty()

    def _set_dirty(self):
        if self._fully_obscured:
            self._dirty = True
        else:
            self._schedule_refresh()

    def _schedule_refresh(self):
        if self._refresh_idle_handler is None:
            logging.debug('Add refresh idle callback')
            self._refresh_idle_handler = \
                    gobject.idle_add(self.__refresh_idle_cb)

    def __refresh_idle_cb(self):
        self.refresh()
        if self._refresh_idle_handler is not None:
            logging.debug('Remove refresh idle callback')
            gobject.source_remove(self._refresh_idle_handler)
            self._refresh_idle_handler = None
        return False

    def set_is_visible(self, visible):
        logging.debug('canvas_visibility_notify_event_cb %r' % visible)
        if visible:
            self._fully_obscured = False
            if self._dirty:
                self._schedule_refresh()
            if self._update_dates_timer is None:
                logging.debug('Adding date updating timer')
                self._update_dates_timer = \
                        gobject.timeout_add_seconds(UPDATE_INTERVAL,
                                            self.__update_dates_timer_cb)
        else:
            self._fully_obscured = True
            if self._update_dates_timer is not None:
                logging.debug('Remove date updating timer')
                gobject.source_remove(self._update_dates_timer)
                self._update_dates_timer = None

    def __update_dates_timer_cb(self):
        self.update_dates()
        return True

class ListView(BaseListView):
    __gtype_name__ = 'ListView'

    __gsignals__ = {
        'detail-clicked': (gobject.SIGNAL_RUN_FIRST,
                           gobject.TYPE_NONE,
                           ([object]))
    }

    def __init__(self):
        BaseListView.__init__(self)

    def create_entry(self):
        entry = CollapsedEntry()
        entry.connect('detail-clicked', self.__entry_activated_cb)
        return entry

    def __entry_activated_cb(self, entry):
        self.emit('detail-clicked', entry)
