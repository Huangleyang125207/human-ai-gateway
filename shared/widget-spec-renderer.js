/* WidgetSpec v1 renderer. Fixed DOM construction only: no HTML/code execution. */
(function widgetSpecRenderer(global) {
  "use strict";

  function toViewModel(data) {
    var rate = data && data.summary ? data.summary.rate : null;
    return {
      metric: typeof rate === "number" ? Math.round(rate * 100) + "%" : "—",
      caption: data && data.summary ? String(data.summary.caption || "") : "",
      values: Array.isArray(data && data.days)
        ? data.days.map(function(day) {
            return typeof day.rate === "number" ? day.rate : null;
          })
        : [],
    };
  }

  function toMemoViewModel(data) {
    return {
      caption: data && data.caption ? String(data.caption) : "",
      items: Array.isArray(data && data.items)
        ? data.items.map(function(item) {
            return {
              occurrenceId: String(item.occurrence_id || ""),
              seriesId: String(item.series_id || ""),
              text: String(item.text || ""),
              dueAt: String(item.due_at || ""),
              state: String(item.state || "pending"),
              overdue: item.overdue === true,
              schedule: item.schedule && typeof item.schedule === "object"
                ? item.schedule : { kind: "once" },
              scheduleLabel: String(item.schedule_label || ""),
              notificationEnabled: item.notification_enabled !== false,
            };
          })
        : [],
    };
  }

  function appendText(parent, className, value) {
    var element = document.createElement("div");
    element.className = className;
    element.textContent = value;
    parent.appendChild(element);
  }

  function dispatchIntent(text) {
    document.dispatchEvent(new CustomEvent("gateway:ai-intent", {
      detail: { text: text },
    }));
  }

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function memoFieldsFromIso(value) {
    var date = value ? new Date(value) : new Date();
    if (Number.isNaN(date.getTime())) date = new Date();
    if (!value) {
      date.setMinutes(0, 0, 0);
      date.setHours(date.getHours() + 1);
    }
    return {
      date: date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate()),
      time: pad(date.getHours()) + ":" + pad(date.getMinutes()),
    };
  }

  function memoIsoFromFields(dateValue, timeValue) {
    var matchDate = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateValue || "");
    var matchTime = /^(\d{2}):(\d{2})$/.exec(timeValue || "");
    if (!matchDate || !matchTime) return "";
    var value = new Date(
      Number(matchDate[1]), Number(matchDate[2]) - 1, Number(matchDate[3]),
      Number(matchTime[1]), Number(matchTime[2]), 0, 0
    );
    if (
      value.getFullYear() !== Number(matchDate[1]) ||
      value.getMonth() !== Number(matchDate[2]) - 1 ||
      value.getDate() !== Number(matchDate[3]) ||
      value.getHours() !== Number(matchTime[1]) ||
      value.getMinutes() !== Number(matchTime[2])
    ) return "";
    return value.toISOString();
  }

  async function memoRequest(path, method, body) {
    var response = await fetch(path, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
    if (!response.ok) {
      var payload = await response.json().catch(function() { return {}; });
      throw new Error(payload.detail && payload.detail.code || "memo_request_failed");
    }
    return response.json();
  }

  function field(label, control) {
    var wrap = document.createElement("label");
    wrap.className = "memo-editor-field";
    appendText(wrap, "memo-editor-label", label);
    wrap.appendChild(control);
    return wrap;
  }

  function actionButton(label, className, onClick) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    button.addEventListener("click", onClick);
    return button;
  }

  function openMemoEditor(root, spec, item) {
    var fields = memoFieldsFromIso(item && item.dueAt);
    var backdrop = document.createElement("div");
    backdrop.className = "memo-editor-backdrop";
    var panel = document.createElement("section");
    panel.className = "memo-editor";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-label", item ? "编辑备忘" : "新增备忘");
    backdrop.appendChild(panel);

    var grip = document.createElement("div");
    grip.className = "memo-editor-grip";
    panel.appendChild(grip);
    appendText(panel, "memo-editor-title", item ? "编辑备忘" : "新增备忘");

    var textInput = document.createElement("textarea");
    textInput.className = "memo-editor-text";
    textInput.maxLength = 200;
    textInput.placeholder = "要记住什么？";
    textInput.value = item ? item.text : "";
    panel.appendChild(field("内容", textInput));

    var when = document.createElement("div");
    when.className = "memo-editor-when";
    var dateInput = document.createElement("input");
    dateInput.className = "memo-editor-input";
    dateInput.type = "date";
    dateInput.value = fields.date;
    when.appendChild(field("日期", dateInput));
    var timeInput = document.createElement("input");
    timeInput.className = "memo-editor-input";
    timeInput.type = "time";
    timeInput.value = fields.time;
    when.appendChild(field("时间", timeInput));
    panel.appendChild(when);

    var schedule = document.createElement("select");
    schedule.className = "memo-editor-input";
    [
      ["once", "单次"], ["daily", "每天"], ["weekdays", "工作日"],
      ["weekly", "每周"], ["monthly", "每月"],
    ].forEach(function(option) {
      var node = document.createElement("option");
      node.value = option[0];
      node.textContent = option[1];
      schedule.appendChild(node);
    });
    schedule.value = item && item.schedule.kind || "once";
    panel.appendChild(field("频率", schedule));

    var notifyLabel = document.createElement("label");
    notifyLabel.className = "memo-editor-notify";
    var notifyCopy = document.createElement("span");
    appendText(notifyCopy, "memo-editor-notify-title", "到点提醒");
    appendText(notifyCopy, "memo-editor-hint", "后台 AI 唤醒服务接入后生效");
    notifyLabel.appendChild(notifyCopy);
    var notify = document.createElement("input");
    notify.type = "checkbox";
    notify.checked = item ? item.notificationEnabled : true;
    notifyLabel.appendChild(notify);
    panel.appendChild(notifyLabel);

    var error = document.createElement("div");
    error.className = "memo-editor-error";
    panel.appendChild(error);
    var controls = [];
    function close() {
      document.removeEventListener("keydown", onKeydown);
      backdrop.remove();
    }
    function busy(value) {
      controls.forEach(function(control) { control.disabled = value; });
    }
    async function run(effect) {
      busy(true);
      error.textContent = "";
      try {
        await effect();
        close();
        await mount(root, spec);
      } catch (requestError) {
        error.textContent = "没有保存成功，请检查后重试";
        busy(false);
      }
    }
    function onKeydown(event) {
      if (event.key === "Escape") close();
    }
    document.addEventListener("keydown", onKeydown);
    backdrop.addEventListener("click", function(event) {
      if (event.target === backdrop) close();
    });

    var save = actionButton("保存", "memo-editor-save", function() {
      var dueAt = memoIsoFromFields(dateInput.value, timeInput.value);
      if (!textInput.value.trim()) {
        error.textContent = "写一句要记住的事";
        return;
      }
      if (!dueAt) {
        error.textContent = "日期或时间格式不对";
        return;
      }
      var selectedSchedule = { kind: schedule.value };
      if (schedule.value === "weekdays") selectedSchedule.weekdays = [1, 2, 3, 4, 5];
      if (schedule.value === "weekly") {
        var weekday = new Date(dueAt).getDay();
        selectedSchedule.weekdays = [weekday === 0 ? 7 : weekday];
      }
      var body = {
        text: textInput.value.trim(),
        due_at: dueAt,
        schedule: selectedSchedule,
        notification_enabled: notify.checked,
      };
      var path = item
        ? "/api/memos/series/" + encodeURIComponent(item.seriesId) +
          "/occurrences/" + encodeURIComponent(item.occurrenceId)
        : "/api/memos";
      run(function() { return memoRequest(path, item ? "PUT" : "POST", body); });
    });
    controls.push(save);
    panel.appendChild(save);

    if (item) {
      appendText(panel, "memo-editor-section-label", "快捷处理");
      var actions = document.createElement("div");
      actions.className = "memo-editor-actions";
      [["推迟 1 小时", "hour"], ["明天此时", "tomorrow"]].forEach(function(preset) {
        var control = actionButton(preset[0], "memo-editor-action", function() {
          var until = new Date();
          until.setHours(until.getHours() + (preset[1] === "hour" ? 1 : 24));
          run(function() {
            return memoRequest(
              "/api/memos/occurrences/" + encodeURIComponent(item.occurrenceId) + "/actions",
              "POST", { action: "snooze", snooze_until: until.toISOString() }
            );
          });
        });
        controls.push(control);
        actions.appendChild(control);
      });
      var skip = actionButton("跳过本次", "memo-editor-action", function() {
        run(function() {
          return memoRequest(
            "/api/memos/occurrences/" + encodeURIComponent(item.occurrenceId) + "/actions",
            "POST", { action: "skip" }
          );
        });
      });
      var archive = actionButton("归档", "memo-editor-action is-danger", function() {
        run(function() {
          return memoRequest(
            "/api/memos/series/" + encodeURIComponent(item.seriesId) + "/actions",
            "POST", { action: "archive" }
          );
        });
      });
      controls.push(skip, archive);
      actions.appendChild(skip);
      actions.appendChild(archive);
      panel.appendChild(actions);
    }

    var ai = actionButton("✦ 交给 AI", "memo-editor-ai", function() {
      close();
      dispatchIntent(item
        ? "帮我进一步处理备忘录「" + item.text + "」："
        : "帮我添加一条备忘录：");
    });
    controls.push(ai);
    panel.appendChild(ai);
    appendText(panel, "memo-editor-ai-hint", "适合图片、模糊时间或需要商量的事情");
    document.body.appendChild(backdrop);
    textInput.focus();
  }

  function renderMemoList(root, spec, data) {
    var model = toMemoViewModel(data);
    root.classList.add("widget-spec", "widget-spec-memo-list");
    appendText(root, "widget-spec-title", spec.title);

    var list = document.createElement("div");
    list.className = "widget-spec-memos";
    if (!model.items.length) {
      appendText(list, "widget-spec-empty", spec.view.empty_text);
    }
    model.items.forEach(function(item) {
      var row = document.createElement("div");
      row.className = "widget-spec-memo" + (item.overdue ? " is-overdue" : "");
      var done = actionButton("", "widget-spec-memo-done", function() {
        done.disabled = true;
        memoRequest(
          "/api/memos/occurrences/" + encodeURIComponent(item.occurrenceId) + "/actions",
          "POST", { action: "complete" }
        ).then(function() { return mount(root, spec); }).catch(function() {
          done.disabled = false;
          done.setAttribute("aria-label", "完成失败，请重试");
        });
      });
      done.setAttribute("aria-label", "完成「" + item.text + "」");
      row.appendChild(done);
      var edit = document.createElement("button");
      edit.type = "button";
      edit.className = "widget-spec-memo-edit";
      var copy = document.createElement("span");
      copy.className = "widget-spec-memo-copy";
      appendText(copy, "widget-spec-memo-text", item.text);
      appendText(
        copy,
        "widget-spec-memo-meta",
        item.scheduleLabel + (item.overdue ? " · 已到时间" : "")
      );
      edit.appendChild(copy);
      edit.addEventListener("click", function() {
        openMemoEditor(root, spec, item);
      });
      row.appendChild(edit);
      list.appendChild(row);
    });
    root.appendChild(list);

    var add = document.createElement("button");
    add.type = "button";
    add.className = "widget-spec-memo-add";
    add.textContent = "＋ " + spec.view.add_label;
    add.addEventListener("click", function() {
      openMemoEditor(root, spec, null);
    });
    root.appendChild(add);
    appendText(root, "widget-spec-caption", model.caption);
  }

  function render(root, spec, data) {
    var isMemo = spec && spec.view && spec.view.type === "memo_list";
    var model = toViewModel(data);
    root.textContent = "";
    if (isMemo) {
      renderMemoList(root, spec, data);
      return;
    }
    root.classList.add("widget-spec", "widget-spec-metric-sparkline");
    appendText(root, "widget-spec-title", spec.title);
    appendText(root, "widget-spec-metric", model.metric);
    appendText(root, "widget-spec-caption", model.caption);

    var series = document.createElement("div");
    series.className = "widget-spec-series";
    series.setAttribute("aria-label", model.caption);
    model.values.forEach(function(value) {
      var bar = document.createElement("span");
      bar.className = "widget-spec-bar" + (value == null ? " is-empty" : "");
      bar.style.height = value == null ? "3px" : (3 + value * 25) + "px";
      series.appendChild(bar);
    });
    root.appendChild(series);
  }

  async function mount(root, spec) {
    root.textContent = "加载中…";
    var response = await fetch("/api/widget-runtime/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(spec),
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error("WidgetSpec query failed: " + response.status);
    }
    var payload = await response.json();
    render(root, spec, payload.data);
  }

  global.gatewayWidgetSpec = {
    mount: mount,
    render: render,
    toViewModel: toViewModel,
    toMemoViewModel: toMemoViewModel,
    memoFieldsFromIso: memoFieldsFromIso,
    memoIsoFromFields: memoIsoFromFields,
  };
})(window);
